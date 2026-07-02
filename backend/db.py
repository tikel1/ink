"""SQLite access layer for the multi-tenant backend."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from .config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id              TEXT PRIMARY KEY,
    token_hash      TEXT NOT NULL,           -- sha256 of the app bearer token
    email           TEXT,
    enc_openai_key  TEXT,                    -- Fernet ciphertext, null = use platform
    use_own_key     INTEGER NOT NULL DEFAULT 0,
    key_required    INTEGER NOT NULL DEFAULT 0,  -- force own key (flip remotely)
    suspended       INTEGER NOT NULL DEFAULT 0,  -- admin can block an account
    is_test         INTEGER NOT NULL DEFAULT 0,  -- dev/test account: excluded from real-cost views
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS devices (
    id           TEXT PRIMARY KEY,           -- hardware id (MAC)
    api_key      TEXT NOT NULL,              -- device secret for /api/display
    account_id   TEXT REFERENCES accounts(id) ON DELETE SET NULL,
    pairing_code TEXT,
    status       TEXT NOT NULL DEFAULT 'unpaired',
    name         TEXT NOT NULL DEFAULT '',   -- user-given label, '' = use default
    tz           TEXT NOT NULL,
    lat          REAL NOT NULL,
    lon          REAL NOT NULL,
    wake_hour    INTEGER NOT NULL DEFAULT 6,
    wake_minute  INTEGER NOT NULL DEFAULT 0,
    language     TEXT NOT NULL DEFAULT 'en',
    temp_unit    TEXT NOT NULL DEFAULT 'c',
    interests    TEXT NOT NULL DEFAULT '',   -- comma separated
    signature    TEXT NOT NULL DEFAULT 'Ink.',
    holiday_jewish  INTEGER NOT NULL DEFAULT 1,
    holiday_israeli INTEGER NOT NULL DEFAULT 1,
    holiday_global  INTEGER NOT NULL DEFAULT 1,
    orientation     TEXT NOT NULL DEFAULT 'landscape',
    show_date       INTEGER NOT NULL DEFAULT 1,
    show_weather    INTEGER NOT NULL DEFAULT 1,
    use_weather     INTEGER NOT NULL DEFAULT 1,   -- location+weather informs the prompt
    use_event       INTEGER NOT NULL DEFAULT 1,   -- a moment in history informs the prompt
    city_name     TEXT NOT NULL DEFAULT '',         -- display name of the location
    auto_timezone INTEGER NOT NULL DEFAULT 1,        -- tz follows the location automatically
    schedule      TEXT NOT NULL DEFAULT 'daily',     -- daily | weekly | custom
    schedule_days TEXT NOT NULL DEFAULT '',          -- comma days for custom, e.g. mon,thu
    power_source  TEXT NOT NULL DEFAULT 'usb',        -- DETECTED state: usb (plugged) | battery
    sleep_after_minutes INTEGER NOT NULL DEFAULT 10,  -- legacy single timeout (superseded below)
    plugged_sleep_minutes INTEGER NOT NULL DEFAULT 0,   -- plugged in: 0 = always on, >0 = sleep after N min
    battery_sleep_minutes INTEGER NOT NULL DEFAULT 10,  -- on battery: sleep after N min
    custom_prompt_override TEXT,
    enabled      INTEGER NOT NULL DEFAULT 1,
    is_test      INTEGER NOT NULL DEFAULT 0,    -- dev/test frame: excluded from real-cost views
    display_order INTEGER NOT NULL DEFAULT 0,   -- user-arranged order on the home carousel
    last_seen    TEXT,
    battery      REAL,
    wifi_rssi    INTEGER,
    fw_version   TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS generation_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id    TEXT NOT NULL,
    account_id   TEXT,
    date         TEXT,                          -- artwork date (local)
    trigger      TEXT NOT NULL DEFAULT 'manual', -- manual | auto
    ok           INTEGER NOT NULL DEFAULT 0,
    duration_ms  INTEGER NOT NULL DEFAULT 0,
    retries      INTEGER NOT NULL DEFAULT 0,
    image_calls  INTEGER NOT NULL DEFAULT 0,
    text_calls   INTEGER NOT NULL DEFAULT 0,
    search_calls INTEGER NOT NULL DEFAULT 0,
    text_tokens  INTEGER NOT NULL DEFAULT 0,
    cost_usd     REAL NOT NULL DEFAULT 0,
    provider     TEXT NOT NULL DEFAULT '',
    phase        TEXT NOT NULL DEFAULT '',       -- last phase reached (failure locus)
    error        TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_calls (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    method     TEXT NOT NULL,
    path       TEXT NOT NULL,
    kind       TEXT NOT NULL DEFAULT 'other',   -- app | media | firmware | other
    device_id  TEXT,
    status     INTEGER NOT NULL,
    ms         INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS daily_artwork (
    device_id      TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    date           TEXT NOT NULL,
    image_path     TEXT,
    archive_path   TEXT,
    event_text_en  TEXT,
    event_text_he  TEXT,
    weather_summary TEXT,
    orientation    TEXT,
    image_prompt   TEXT,                       -- the full prompt sent to the image model
    event_caption  TEXT,                       -- the chosen event (caption)
    event_visual   TEXT,                       -- the iconic visual depicted ('' = abstract)
    other_events   TEXT,                       -- JSON: date-verified runner-up events not chosen
    status         TEXT NOT NULL DEFAULT 'pending',
    created_at     TEXT NOT NULL,
    PRIMARY KEY (device_id, date)
);
"""


# Columns added after the first release — applied to existing DBs on startup.
_MIGRATIONS = {
    "orientation": "TEXT NOT NULL DEFAULT 'landscape'",
    "show_date": "INTEGER NOT NULL DEFAULT 1",
    "show_weather": "INTEGER NOT NULL DEFAULT 1",
    "name": "TEXT NOT NULL DEFAULT ''",
    "city_name": "TEXT NOT NULL DEFAULT ''",
    "auto_timezone": "INTEGER NOT NULL DEFAULT 1",
    "schedule": "TEXT NOT NULL DEFAULT 'daily'",
    "schedule_days": "TEXT NOT NULL DEFAULT ''",
    "power_source": "TEXT NOT NULL DEFAULT 'usb'",
    "sleep_after_minutes": "INTEGER NOT NULL DEFAULT 10",
    "plugged_sleep_minutes": "INTEGER NOT NULL DEFAULT 0",   # plugged: 0 = always on, >0 = sleep after N min
    "battery_sleep_minutes": "INTEGER NOT NULL DEFAULT 10",  # on battery: sleep after N min
    "sleeping": "INTEGER NOT NULL DEFAULT 0",   # frame reported deep sleep
    "pending_command": "TEXT NOT NULL DEFAULT ''",  # one-shot cmd the frame picks up on its next poll
    "date_format": "TEXT NOT NULL DEFAULT 'weekday'",  # embedded-date style
    "wake_minute": "INTEGER NOT NULL DEFAULT 0",  # minute of the daily update time
    "use_weather": "INTEGER NOT NULL DEFAULT 1",  # location+weather informs the prompt
    "use_event": "INTEGER NOT NULL DEFAULT 1",    # a moment in history informs the prompt
    "last_auto_gen": "TEXT NOT NULL DEFAULT ''",  # date (YYYY-MM-DD) the scheduler last auto-generated
    "ota_error": "TEXT NOT NULL DEFAULT ''",   # last OTA failure code the frame reported ('' = none)
    "display_order": "INTEGER NOT NULL DEFAULT 0",  # home-carousel order
    "is_test": "INTEGER NOT NULL DEFAULT 0",   # dev/test frame flag
}

# Columns added to the accounts table after the first release.
_ACCOUNT_MIGRATIONS = {
    "suspended": "INTEGER NOT NULL DEFAULT 0",
    "is_test": "INTEGER NOT NULL DEFAULT 0",   # dev/test account flag
}

# Columns added to the daily_artwork table after the first release.
_ARTWORK_MIGRATIONS = {
    "orientation": "TEXT",
    "image_prompt": "TEXT",
    "event_caption": "TEXT",
    "event_visual": "TEXT",
    "other_events": "TEXT",   # JSON list of date-verified runner-up events
}


def _migrate(conn, table: str, migrations: dict) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    for column, ddl in migrations.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn, "devices", _MIGRATIONS)
        _migrate(conn, "accounts", _ACCOUNT_MIGRATIONS)
        _migrate(conn, "daily_artwork", _ARTWORK_MIGRATIONS)
        # Indexes for the hot lookups (token on every authed call, pairing code on
        # pair, account_id on every device list). All non-unique: enforcing UNIQUE
        # retroactively would abort startup on any legacy DB with duplicate rows,
        # and lookup speed doesn't need it.
        conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_accounts_token_hash ON accounts(token_hash);
            CREATE INDEX IF NOT EXISTS idx_devices_pairing_code ON devices(pairing_code);
            CREATE INDEX IF NOT EXISTS idx_devices_account_id ON devices(account_id);
        """)
        # WAL: readers don't block behind writers (frame polls + app requests
        # overlap constantly). Sticky once set.
        conn.execute("PRAGMA journal_mode=WAL;")


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    settings = get_settings()
    conn = sqlite3.connect(settings.db_path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
    finally:
        conn.close()
