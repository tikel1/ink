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
    city_name     TEXT NOT NULL DEFAULT '',         -- display name of the location
    auto_timezone INTEGER NOT NULL DEFAULT 1,        -- tz follows the location automatically
    schedule      TEXT NOT NULL DEFAULT 'daily',     -- daily | weekly | custom
    schedule_days TEXT NOT NULL DEFAULT '',          -- comma days for custom, e.g. mon,thu
    power_source  TEXT NOT NULL DEFAULT 'usb',        -- usb (always on) | battery (sleeps)
    sleep_after_minutes INTEGER NOT NULL DEFAULT 10,  -- battery: stay awake this long, then sleep
    custom_prompt_override TEXT,
    enabled      INTEGER NOT NULL DEFAULT 1,
    last_seen    TEXT,
    battery      REAL,
    wifi_rssi    INTEGER,
    fw_version   TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_artwork (
    device_id      TEXT NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    date           TEXT NOT NULL,
    image_path     TEXT,
    archive_path   TEXT,
    event_text_en  TEXT,
    event_text_he  TEXT,
    weather_summary TEXT,
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
}


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(devices)")}
        for column, ddl in _MIGRATIONS.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE devices ADD COLUMN {column} {ddl}")


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
