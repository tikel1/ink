"""Admin monitoring API. Everything here is gated by the ADMIN_TOKEN
(X-Admin-Token header) via AdminDep — it exposes all frames, prompts, costs, and
account ids across the whole deployment, so it is never account-scoped."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from . import artwork_repo, auth, firmware_repo, generation, monitoring_repo, repositories, storage

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[auth.AdminDep])

ONLINE_WINDOW_S = 180
# Preset interest chips offered in the app (mirror of static INTEREST_CHIPS).
# Anything else in a frame's interests is user-entered custom text. 'israel' is
# the default applied to a brand-new frame.
PRESET_INTERESTS = {"israel", "science", "history", "sports", "astronomy", "art", "music", "cinema"}
DEFAULT_INTEREST = "israel"


def _age_seconds(last_seen: str | None) -> float | None:
    if not last_seen:
        return None
    try:
        dt = datetime.fromisoformat(last_seen)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds()


def _state(device) -> str:
    if device.sleeping:
        return "sleep"
    age = _age_seconds(device.last_seen)
    if age is not None and age < ONLINE_WINDOW_S:
        return "online"
    return "offline"


def _interests(device) -> dict:
    """Split a device's interests into preset chips vs user custom text, list the
    active holiday categories, and flag the lone-default ('israel') case."""
    tokens = [t.strip() for t in (device.interests or "").split(",") if t.strip()]
    return {
        "interests_preset": [t for t in tokens if t.lower() in PRESET_INTERESTS],
        "interests_custom": [t for t in tokens if t.lower() not in PRESET_INTERESTS],
        "interests_default": DEFAULT_INTEREST if tokens == [DEFAULT_INTEREST] else None,
        "holidays": [n for n, on in (("Jewish", device.holiday_jewish),
                                     ("Israeli", device.holiday_israeli),
                                     ("Global", device.holiday_global)) if on],
    }


def _frame(device, latest) -> dict:
    return {
        "id": device.id,
        "name": device.name or "",
        **_interests(device),
        "account_id": device.account_id,
        "status": device.status,
        "state": _state(device),
        "last_seen": device.last_seen,
        "battery": device.battery,
        "wifi_rssi": device.wifi_rssi,
        "fw_version": device.fw_version,
        "latest_fw": firmware_repo.latest_version(),
        "update_available": firmware_repo.update_available(device.fw_version),
        "ota_error": device.ota_error,
        "enabled": device.enabled,
        "orientation": device.orientation,
        "wake_hour": device.wake_hour,
        "wake_minute": device.wake_minute,
        "sleep_after_minutes": device.sleep_after_minutes,
        "schedule": device.schedule,
        "created_at": device.created_at,
        "last_art_date": latest.date if latest else None,
        "last_art_caption": (latest.event_caption or latest.event_text_en) if latest else None,
        "image_url": storage.current_url(device.id),
    }


@router.get("/overview")
async def overview() -> dict:
    devices = repositories.list_all_devices()
    states = [_state(d) for d in devices]
    gen = monitoring_repo.generation_stats(days=30)
    api = monitoring_repo.api_call_stats(days=14)
    art = artwork_repo.counts()
    t = gen["totals"]
    runs = t.get("runs") or 0
    ok = t.get("ok") or 0
    return {
        "accounts": repositories.count_accounts(),
        "frames": {
            "total": len(devices),
            "online": states.count("online"),
            "sleep": states.count("sleep"),
            "offline": states.count("offline"),
            "update_available": sum(
                1 for d in devices if firmware_repo.update_available(d.fw_version)),
        },
        "latest_fw": firmware_repo.latest_version(),
        "artwork": art,
        "generation": {
            "runs": runs,
            "ok": ok,
            "failed": runs - ok,
            "success_rate": round(ok / runs, 3) if runs else None,
            "cost_usd": round(t.get("cost") or 0, 2),
            "retries": t.get("retries") or 0,
            "avg_ms": round(t.get("avg_ms") or 0),
            "images": t.get("images") or 0,
            "text_calls": t.get("texts") or 0,
            "search_calls": t.get("searches") or 0,
            "tokens": t.get("tokens") or 0,
            "by_day": gen["by_day"],
        },
        "api": api,
    }


@router.get("/frames")
async def frames() -> dict:
    suspended = {a.id: a.suspended for a in repositories.list_accounts(limit=500)}
    out = []
    for d in repositories.list_all_devices():
        fr = _frame(d, artwork_repo.latest_ready(d.id))
        fr["account_suspended"] = suspended.get(d.account_id) if d.account_id else None
        out.append(fr)
    return {"frames": out}


@router.get("/generations")
async def generations(limit: int = 100, device: str | None = None,
                      failed: bool = False) -> dict:
    return {"runs": monitoring_repo.list_generation_runs(
        limit=min(limit, 500), device_id=device, only_failed=failed)}


@router.get("/gallery")
async def gallery(limit: int = 120) -> dict:
    devices = {d.id: d for d in repositories.list_all_devices()}
    items = []
    for a in artwork_repo.list_all_ready(limit=min(limit, 500)):
        # Skip rows whose image file is gone — they'd render as a broken thumbnail.
        if not generation.archive_image_path(a.device_id, a.date).exists():
            continue
        dev = devices.get(a.device_id)
        items.append({
            "device_id": a.device_id,
            "device_name": (dev.name if dev else "") or "",
            **(_interests(dev) if dev else {}),
            "date": a.date,
            "image_url": storage.archive_url(a.device_id, a.date),
            "caption": a.event_caption or a.event_text_en,
            "event_caption": a.event_caption,
            "event_visual": a.event_visual,
            "event_text_en": a.event_text_en,
            "event_text_he": a.event_text_he,
            "weather_summary": a.weather_summary,
            "image_prompt": a.image_prompt,
            "orientation": a.orientation,
            "created_at": a.created_at,
        })
    return {"items": items}


@router.get("/api-calls")
async def api_calls(limit: int = 200) -> dict:
    return {
        "calls": monitoring_repo.list_api_calls(limit=min(limit, 1000)),
        "stats": monitoring_repo.api_call_stats(days=14),
    }


# --------------------------------------------------------------------------- #
# Account management
# --------------------------------------------------------------------------- #
@router.get("/accounts")
async def accounts() -> dict:
    out = []
    for a in repositories.list_accounts(limit=500):
        devices = repositories.list_account_devices(a.id)
        last = max((d.last_seen for d in devices if d.last_seen), default=None)
        out.append({
            "id": a.id,
            "email": a.email,
            "created_at": a.created_at,
            "suspended": a.suspended,
            "device_count": len(devices),
            "last_active": last,
            "has_own_key": a.use_own_key,
        })
    return {"accounts": out}


@router.post("/frames/{device_id}/enable")
async def set_frame_enabled(device_id: str, enabled: bool = True) -> dict:
    """Enable/disable a single frame (device.enabled). A disabled frame is skipped
    by the scheduler — deactivates just this frame, not its whole account."""
    if repositories.get_device(device_id) is None:
        raise HTTPException(status_code=404, detail="frame not found")
    repositories.update_device_config(device_id, enabled=enabled)
    return {"device_id": device_id, "enabled": enabled}


@router.post("/accounts/{account_id}/suspend")
async def set_suspended(account_id: str, suspended: bool = True) -> dict:
    """Deactivate (suspend) or reactivate an account. Suspended accounts are
    blocked from the app and skipped by the generation scheduler — reversible."""
    if repositories.get_account(account_id) is None:
        raise HTTPException(status_code=404, detail="account not found")
    repositories.set_account_suspended(account_id, suspended)
    return {"account_id": account_id, "suspended": suspended}


@router.delete("/accounts/{account_id}")
async def remove_account(account_id: str) -> dict:
    """Permanently delete an account. Its frames are unbound (returned to
    re-pairable), artwork rows survive; the account row is removed."""
    if repositories.get_account(account_id) is None:
        raise HTTPException(status_code=404, detail="account not found")
    repositories.delete_account(account_id)
    return {"deleted": account_id}
