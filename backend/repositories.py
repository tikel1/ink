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
               (id, api_key, pairing_code, status, tz, lat, lon, wake_hour, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                device_id,
                secrets.token_urlsafe(24),
                _new_pairing_code(),
                _UNPAIRED,
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
                 tz = ?, lat = ?, lon = ?, wake_hour = ?,
                 language = 'en', temp_unit = 'c', interests = '',
                 signature = 'House Kaplan',
                 holiday_jewish = 1, holiday_israeli = 1, holiday_global = 1,
                 custom_prompt_override = NULL, enabled = 1
               WHERE id = ?""",
            (
                _UNPAIRED, _new_pairing_code(),
                settings.default_tz, settings.default_lat, settings.default_lon,
                settings.default_wake_hour, device_id,
            ),
        )


def list_account_devices(account_id: str) -> list[Device]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM devices WHERE account_id = ? ORDER BY created_at",
            (account_id,),
        ).fetchall()
        return [Device.from_row(r) for r in rows]


def list_enabled_paired_devices() -> list[Device]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM devices WHERE status = ? AND enabled = 1",
            (_PAIRED,),
        ).fetchall()
        return [Device.from_row(r) for r in rows]


def update_device_config(device_id: str, **fields: object) -> None:
    allowed = {
        "tz", "lat", "lon", "wake_hour", "language", "temp_unit", "interests",
        "signature", "holiday_jewish", "holiday_israeli", "holiday_global",
        "custom_prompt_override", "enabled",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    columns = ", ".join(f"{k} = ?" for k in updates)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE devices SET {columns} WHERE id = ?",
            list(updates.values()) + [device_id],
        )


def update_telemetry(device_id: str, **fields: object) -> None:
    with get_connection() as conn:
        conn.execute(
            """UPDATE devices SET last_seen = ?, battery = ?, wifi_rssi = ?,
               fw_version = ? WHERE id = ?""",
            (
                now_iso(),
                fields.get("battery"),
                fields.get("wifi_rssi"),
                fields.get("fw_version"),
                device_id,
            ),
        )
