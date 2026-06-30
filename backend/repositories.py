"""Repository layer — the only place that issues SQL (parameterized)."""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Optional

from .config import get_settings
from .db import get_connection
from .models import Account, Device

_UNPAIRED = "unpaired"
_PAIRED = "paired"
_PAIRING_MIN = 100_000
_PAIRING_MAX = 999_999
_DEFAULT_SIGNATURE = "Ink."

# Power auto-detection from the battery-pad voltage the frame reports each poll.
# The XIAO's BAT pad reads ~0 V when running on USB with no cell, and a real cell
# reads ~3.0–4.1 V while discharging; a charging/full cell sits at/above this. So
# anything outside the discharging band is treated as "plugged in". This is what
# lets the app stop asking the user whether the frame is plugged or on battery.
_BATTERY_MIN_V = 3.0    # below this: no cell sensed -> on USB
_BATTERY_MAX_V = 4.15   # at/above this: charging/plugged -> on USB


def detect_power_source(battery_v: Optional[float]) -> Optional[str]:
    """'battery' | 'usb' from a reported pad voltage, or None when unknown (so the
    last known state is kept rather than guessed)."""
    if battery_v is None:
        return None
    return "battery" if _BATTERY_MIN_V <= battery_v < _BATTERY_MAX_V else "usb"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_pairing_code() -> str:
    return str(_PAIRING_MIN + secrets.randbelow(_PAIRING_MAX - _PAIRING_MIN + 1))


# --------------------------------------------------------------------------- #
# Accounts
# --------------------------------------------------------------------------- #
def create_account(token_hash: str, email: Optional[str] = None) -> Account:
    account_id = secrets.token_urlsafe(12)
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO accounts (id, token_hash, email, created_at)
               VALUES (?, ?, ?, ?)""",
            (account_id, token_hash, email, now_iso()),
        )
    return get_account(account_id)  # type: ignore[return-value]


def get_account(account_id: str) -> Optional[Account]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM accounts WHERE id = ?", (account_id,)
        ).fetchone()
        return Account.from_row(row) if row else None


def get_account_by_token_hash(token_hash: str) -> Optional[Account]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM accounts WHERE token_hash = ?", (token_hash,)
        ).fetchone()
        return Account.from_row(row) if row else None


def set_account_key(account_id: str, enc_key: Optional[str]) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE accounts SET enc_openai_key = ?, use_own_key = ? WHERE id = ?",
            (enc_key, 1 if enc_key else 0, account_id),
        )


def set_key_required(account_id: str, required: bool) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE accounts SET key_required = ? WHERE id = ?",
            (1 if required else 0, account_id),
        )


def set_account_suspended(account_id: str, suspended: bool) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE accounts SET suspended = ? WHERE id = ?",
            (1 if suspended else 0, account_id),
        )


def set_account_token_hash(account_id: str, token_hash: str) -> None:
    """Replace the account's bearer-token hash (used to mint a recovery token).
    Caller hashes the plaintext via auth.hash_token to avoid leaking it here."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE accounts SET token_hash = ? WHERE id = ?",
            (token_hash, account_id),
        )


def list_accounts(query: str = "", limit: int = 100) -> list[Account]:
    """All accounts, or those whose id/email contains `query` (admin search)."""
    with get_connection() as conn:
        if query:
            like = f"%{query}%"
            rows = conn.execute(
                """SELECT * FROM accounts WHERE id LIKE ? OR email LIKE ?
                   ORDER BY created_at DESC LIMIT ?""",
                (like, like, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM accounts ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [Account.from_row(r) for r in rows]


def delete_account(account_id: str) -> None:
    """Unbind the account's frames (back to fresh, re-pairable) then remove the
    account row. Devices/artwork survive as unpaired so hardware isn't bricked."""
    for device in list_account_devices(account_id):
        unbind_device(device.id)
    with get_connection() as conn:
        conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))


# --------------------------------------------------------------------------- #
# Devices
# --------------------------------------------------------------------------- #
def register_device(device_id: str) -> Device:
    existing = get_device(device_id)
    if existing:
        return existing
    settings = get_settings()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO devices
               (id, api_key, pairing_code, status, signature, orientation, tz, lat, lon, wake_hour, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                device_id,
                secrets.token_urlsafe(24),
                _new_pairing_code(),
                _UNPAIRED,
                _DEFAULT_SIGNATURE,
                "portrait",                      # frames ship portrait by default
                settings.default_tz,
                settings.default_lat,
                settings.default_lon,
                settings.default_wake_hour,
                now_iso(),
            ),
        )
    return get_device(device_id)  # type: ignore[return-value]


def get_device(device_id: str) -> Optional[Device]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM devices WHERE id = ?", (device_id,)
        ).fetchone()
        return Device.from_row(row) if row else None


def get_device_by_pairing_code(code: str) -> Optional[Device]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM devices WHERE pairing_code = ?", (code,)
        ).fetchone()
        return Device.from_row(row) if row else None


def bind_device(device_id: str, account_id: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """UPDATE devices SET account_id = ?, status = ?, pairing_code = NULL
               WHERE id = ?""",
            (account_id, _PAIRED, device_id),
        )


def unbind_device(device_id: str) -> None:
    """Server-side reset: detach from its account, forget all preferences, and
    reissue a pairing code so the frame can be re-assigned to a new account."""
    settings = get_settings()
    with get_connection() as conn:
        conn.execute(
            """UPDATE devices SET
                 account_id = NULL, status = ?, pairing_code = ?,
                 name = '',
                 tz = ?, lat = ?, lon = ?, wake_hour = ?, wake_minute = 0,
                 language = 'en', temp_unit = 'c', interests = '',
                 signature = ?,
                 holiday_jewish = 1, holiday_israeli = 1, holiday_global = 1,
                 orientation = 'landscape', show_date = 1, show_weather = 1, use_weather = 1, use_event = 1,
                 city_name = '', auto_timezone = 1, schedule = 'daily', schedule_days = '',
                 power_source = 'usb', sleep_after_minutes = 10,
                 plugged_sleep_minutes = 0, battery_sleep_minutes = 10,
                 custom_prompt_override = NULL, enabled = 1
               WHERE id = ?""",
            (
                _UNPAIRED, _new_pairing_code(),
                settings.default_tz, settings.default_lat, settings.default_lon,
                settings.default_wake_hour, _DEFAULT_SIGNATURE, device_id,
            ),
        )


def list_account_devices(account_id: str) -> list[Device]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM devices WHERE account_id = ? ORDER BY display_order, created_at",
            (account_id,),
        ).fetchall()
        return [Device.from_row(r) for r in rows]


def set_device_order(account_id: str, ordered_ids: list[str]) -> None:
    """Persist the user's home-carousel order. Only reorders devices the account
    owns (the device_id list is validated by the caller); position = list index."""
    with get_connection() as conn:
        for position, device_id in enumerate(ordered_ids):
            conn.execute(
                "UPDATE devices SET display_order = ? WHERE id = ? AND account_id = ?",
                (position, device_id, account_id),
            )


def list_enabled_paired_devices() -> list[Device]:
    # Skip devices whose account is suspended — the scheduler must not generate for
    # a blocked account.
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT d.* FROM devices d
               JOIN accounts a ON a.id = d.account_id
               WHERE d.status = ? AND d.enabled = 1 AND a.suspended = 0""",
            (_PAIRED,),
        ).fetchall()
        return [Device.from_row(r) for r in rows]


def update_device_config(device_id: str, **fields: object) -> None:
    allowed = {
        "name",
        "tz", "lat", "lon", "wake_hour", "wake_minute", "language", "temp_unit", "interests",
        "signature", "holiday_jewish", "holiday_israeli", "holiday_global",
        "orientation", "show_date", "date_format", "show_weather", "use_weather", "use_event",
        "city_name", "auto_timezone", "schedule", "schedule_days",
        "plugged_sleep_minutes", "battery_sleep_minutes",
        "custom_prompt_override", "enabled",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    # If the schedule or update time changed, re-arm today's automatic generation
    # so the scheduler fires at the NEW time today (even if it already ran earlier).
    if any(k in updates for k in ("wake_hour", "wake_minute", "schedule", "schedule_days")):
        updates["last_auto_gen"] = ""
    columns = ", ".join(f"{k} = ?" for k in updates)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE devices SET {columns} WHERE id = ?",
            list(updates.values()) + [device_id],
        )


def mark_auto_generated(device_id: str, date_str: str) -> None:
    """Record that the scheduler auto-generated for this device on `date_str`,
    so it fires once per day (independent of manual regenerations)."""
    with get_connection() as conn:
        conn.execute("UPDATE devices SET last_auto_gen = ? WHERE id = ?",
                     (date_str, device_id))


def set_pending_command(device_id: str, command: str) -> None:
    """Queue a one-shot command (e.g. 'refresh', 'sleep') the frame picks up on
    its next version poll."""
    with get_connection() as conn:
        conn.execute("UPDATE devices SET pending_command = ? WHERE id = ?",
                     (command, device_id))


def set_ota_result(device_id: str, code: str) -> None:
    """Record an OTA failure code the frame reported (so the app can show it)."""
    with get_connection() as conn:
        conn.execute("UPDATE devices SET ota_error = ? WHERE id = ?", (code, device_id))


def clear_ota_result(device_id: str) -> None:
    """Clear before a fresh OTA attempt so a stale failure isn't shown again."""
    with get_connection() as conn:
        conn.execute("UPDATE devices SET ota_error = '' WHERE id = ?", (device_id,))


def take_pending_command(device_id: str) -> str:
    """Read + clear the pending command (delivered exactly once)."""
    with get_connection() as conn:
        row = conn.execute("SELECT pending_command FROM devices WHERE id = ?",
                           (device_id,)).fetchone()
        cmd = (row["pending_command"] if row else "") or ""
        if cmd:
            conn.execute("UPDATE devices SET pending_command = '' WHERE id = ?", (device_id,))
        return cmd


def update_telemetry(device_id: str, **fields: object) -> None:
    # A check-in means the frame is awake — clear the sleeping flag. Only overwrite
    # battery/rssi/firmware when the check-in actually carried them (COALESCE keeps
    # the last known value), so a bare poll doesn't wipe them back to NULL.
    # The frame's power state is auto-detected from the reported pad voltage (the
    # user no longer declares it); keep the last known state when voltage is absent.
    battery = fields.get("battery")
    detected = detect_power_source(battery if isinstance(battery, (int, float)) else None)
    with get_connection() as conn:
        conn.execute(
            """UPDATE devices SET last_seen = ?, sleeping = 0,
               battery = COALESCE(?, battery),
               wifi_rssi = COALESCE(?, wifi_rssi),
               fw_version = COALESCE(?, fw_version),
               power_source = COALESCE(?, power_source)
               WHERE id = ?""",
            (
                now_iso(),
                battery,
                fields.get("wifi_rssi"),
                fields.get("fw_version"),
                detected,
                device_id,
            ),
        )


def mark_sleeping(device_id: str) -> None:
    """Frame reported it's entering deep sleep — flag it so the app shows
    'Asleep' immediately instead of waiting for a missed check-in to time out."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE devices SET last_seen = ?, sleeping = 1 WHERE id = ?",
            (now_iso(), device_id),
        )
