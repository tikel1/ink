"""Admin monitoring API. Everything here is gated by the ADMIN_TOKEN
(X-Admin-Token header) via AdminDep — it exposes all frames, prompts, costs, and
account ids across the whole deployment, so it is never account-scoped."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from . import (artwork_repo, auth, costs, firmware_repo, generation, monitoring_repo,
               openai_costs, repositories, storage)
from .config import get_settings

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


def _filter_devices(devices, device_id=None, account_id=None, status=None):
    """Narrow a device list by the global filters. `status` accepts the frame
    lifecycle values used by the console: active | deactivated | online | sleep |
    offline (the connectivity states imply enabled)."""
    out = devices
    if device_id:
        out = [d for d in out if d.id == device_id]
    if account_id:
        out = [d for d in out if d.account_id == account_id]
    if status == "active":
        out = [d for d in out if d.enabled]
    elif status == "deactivated":
        out = [d for d in out if not d.enabled]
    elif status in ("online", "sleep", "offline"):
        out = [d for d in out if d.enabled and _state(d) == status]
    return out


# Map the console's ?test= query value to the tri-state used by the repo layer.
_TEST_MODES = {"test": True, "real": False}


def _test_flag(test: str | None):
    return _TEST_MODES.get(test)  # None (all) for anything unrecognised


def _test_ids() -> tuple[set, set]:
    """(test account ids, test device ids). A device counts as test if flagged
    itself OR owned by a test account, so callers get one authoritative set."""
    accts = {a.id for a in repositories.list_accounts(limit=1000) if a.is_test}
    devs = {d.id for d in repositories.list_all_devices()
            if d.is_test or (d.account_id in accts)}
    return accts, devs


def _apply_test(devices, flag, test_device_ids):
    if flag is True:
        return [d for d in devices if d.id in test_device_ids]
    if flag is False:
        return [d for d in devices if d.id not in test_device_ids]
    return devices


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
        "is_test": device.is_test,
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
async def overview(start: str | None = None, end: str | None = None,
                   device: str | None = None, account: str | None = None,
                   test: str | None = None) -> dict:
    tflag = _test_flag(test)
    tacc, tdev = _test_ids()
    all_devices = repositories.list_all_devices()
    # Fleet counts honor the frame/account/test filters (not date — they're live state).
    devices = _apply_test(_filter_devices(all_devices, device_id=device, account_id=account),
                          tflag, tdev)
    active = [d for d in devices if d.enabled]        # deactivated frames excluded from the live buckets
    states = [_state(d) for d in active]
    # "Active" = enabled and checked in within 48h (online frames poll ~1/min;
    # healthy sleepers wake daily) — a single health number instead of 3 buckets.
    active_48h = sum(1 for d in active
                     if (_age_seconds(d.last_seen) or 1e12) < 48 * 3600)
    tkw = {"test_account_ids": tacc, "test_device_ids": tdev}
    gen = monitoring_repo.generation_stats(start=start, end=end, device_id=device,
                                            account_id=account, test=tflag, **tkw)
    api = monitoring_repo.api_call_stats(start=start, end=end, device_id=device,
                                         test=tflag, test_device_ids=tdev)
    # Real-vs-test cost split over the same window, shown regardless of the filter.
    gen_real = monitoring_repo.generation_stats(start=start, end=end, device_id=device,
                                                account_id=account, test=False, **tkw)["totals"]
    gen_test = monitoring_repo.generation_stats(start=start, end=end, device_id=device,
                                                account_id=account, test=True, **tkw)["totals"]
    art = artwork_repo.counts()
    t = gen["totals"]
    runs = t.get("runs") or 0
    ok = t.get("ok") or 0
    return {
        "accounts": repositories.count_accounts(),
        "frames": {
            "total": len(devices),
            "active": len(active),
            "active_48h": active_48h,
            "online": states.count("online"),
            "sleep": states.count("sleep"),
            "offline": states.count("offline"),
            "deactivated": len(devices) - len(active),
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
        "costs": {**_cost_breakdown(t),
                  "real_estimate_usd": _cost_breakdown(gen_real)["total_usd"],
                  "test_estimate_usd": _cost_breakdown(gen_test)["total_usd"],
                  "test_runs": gen_test.get("runs") or 0,
                  "openai_actual": await openai_costs.fetch(start=start, end=end),
                  "fly_monthly_usd": get_settings().fly_monthly_usd},
        "api": api,
    }


def _cost_breakdown(totals: dict) -> dict:
    """Estimated OpenAI spend split by call type, from the tracked call counts.
    Text/search usually run on Gemini's free tier, so image generation dominates."""
    images = totals.get("images") or 0
    searches = totals.get("searches") or 0
    text_calls = totals.get("texts") or 0
    tokens = totals.get("tokens") or 0
    image_usd = round(images * costs.IMAGE_COST_USD["medium"], 2)
    search_usd = round(searches * costs.SEARCH_COST_USD, 2)
    text_usd = round((tokens / 1000.0) * costs.TEXT_COST_PER_1K if tokens
                     else text_calls * costs.TEXT_FALLBACK_PER_CALL, 2)
    return {
        "estimated": True,
        "items": [
            {"type": "Image generation", "calls": images, "unit": f"${costs.IMAGE_COST_USD['medium']:.2f}/image", "usd": image_usd},
            {"type": "Web search", "calls": searches, "unit": f"${costs.SEARCH_COST_USD:.2f}/call", "usd": search_usd},
            {"type": "Text (event pick · checker · narration)", "calls": text_calls, "unit": f"{tokens:,} tokens", "usd": text_usd},
        ],
        "total_usd": round(image_usd + search_usd + text_usd, 2),
    }


@router.get("/frames")
async def frames(device: str | None = None, account: str | None = None,
                 status: str | None = None, test: str | None = None) -> dict:
    accounts = repositories.list_accounts(limit=500)
    suspended = {a.id: a.suspended for a in accounts}
    test_accts = {a.id for a in accounts if a.is_test}
    tflag = _test_flag(test)
    _, tdev = _test_ids()
    devices = _apply_test(_filter_devices(repositories.list_all_devices(),
                          device_id=device, account_id=account, status=status), tflag, tdev)
    out = []
    for d in devices:
        fr = _frame(d, artwork_repo.latest_ready(d.id))
        fr["account_suspended"] = suspended.get(d.account_id) if d.account_id else None
        fr["account_is_test"] = (d.account_id in test_accts) if d.account_id else False
        fr["test"] = d.is_test or fr["account_is_test"]
        out.append(fr)
    return {"frames": out}


@router.get("/generations")
async def generations(limit: int = 100, device: str | None = None,
                      failed: bool = False, start: str | None = None,
                      end: str | None = None, account: str | None = None,
                      test: str | None = None) -> dict:
    tacc, tdev = _test_ids()
    runs = monitoring_repo.list_generation_runs(
        limit=min(limit, 500), device_id=device, only_failed=failed,
        start=start, end=end, account_id=account, test=_test_flag(test),
        test_account_ids=tacc, test_device_ids=tdev)
    for r in runs:  # badge each row so the console can flag test runs in "All" mode
        r["test"] = r.get("device_id") in tdev or r.get("account_id") in tacc
    return {"runs": runs}


@router.get("/gallery")
async def gallery(limit: int = 120, start: str | None = None, end: str | None = None,
                  device: str | None = None, account: str | None = None,
                  test: str | None = None) -> dict:
    all_devices = {d.id: d for d in repositories.list_all_devices()}
    _, tdev = _test_ids()
    # Which device ids pass the frame/account/test filter (gallery has no status concept).
    allowed = {d.id for d in _apply_test(_filter_devices(list(all_devices.values()),
                                         device_id=device, account_id=account),
                                         _test_flag(test), tdev)}
    items = []
    for a in artwork_repo.list_all_ready(limit=min(limit, 500)):
        if a.device_id not in allowed:
            continue
        if start and a.date < start:
            continue
        if end and a.date > end:
            continue
        # Skip rows whose image file is gone — they'd render as a broken thumbnail.
        if not generation.archive_image_path(a.device_id, a.date).exists():
            continue
        dev = all_devices.get(a.device_id)
        items.append({
            "device_id": a.device_id,
            "test": a.device_id in tdev,
            "device_name": (dev.name if dev else "") or "",
            **(_interests(dev) if dev else {}),
            "date": a.date,
            "image_url": storage.archive_url(a.device_id, a.date),
            # Full-detail original for the preview modal (None once pruned).
            "image_full_url": (storage.archive_original_url(a.device_id, a.date)
                               if generation.archive_original_path(a.device_id, a.date).exists()
                               else None),
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
async def api_calls(limit: int = 200, start: str | None = None, end: str | None = None,
                    device: str | None = None, test: str | None = None) -> dict:
    tflag = _test_flag(test)
    _, tdev = _test_ids()
    calls = monitoring_repo.list_api_calls(limit=min(limit, 1000), start=start, end=end,
                                           device_id=device, test=tflag, test_device_ids=tdev)
    for c in calls:  # badge each row so the console can flag test traffic
        c["test"] = c.get("device_id") in tdev
    return {
        "calls": calls,
        "stats": monitoring_repo.api_call_stats(start=start, end=end, device_id=device,
                                                test=tflag, test_device_ids=tdev),
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
            "is_test": a.is_test,
            "device_count": len(devices),
            "last_active": last,
            "has_own_key": a.use_own_key,
        })
    return {"accounts": out}


@router.post("/accounts/purge-empty")
async def purge_empty_accounts() -> dict:
    """Delete every account with no paired frames (the anonymous accounts the app
    mints on first launch that never paired). Frames are unaffected."""
    removed = 0
    for a in repositories.list_accounts(limit=1000):
        if not repositories.list_account_devices(a.id):
            repositories.delete_account(a.id)
            removed += 1
    return {"deleted": removed}


@router.post("/frames/{device_id}/enable")
async def set_frame_enabled(device_id: str, enabled: bool = True) -> dict:
    """Enable/disable a single frame (device.enabled). A disabled frame is skipped
    by the scheduler — deactivates just this frame, not its whole account."""
    if repositories.get_device(device_id) is None:
        raise HTTPException(status_code=404, detail="frame not found")
    repositories.update_device_config(device_id, enabled=enabled)
    return {"device_id": device_id, "enabled": enabled}


@router.post("/frames/{device_id}/test")
async def set_frame_test(device_id: str, test: bool = True) -> dict:
    """Flag/unflag a single frame as a dev/test frame (its runs + calls are then
    split out of the real-cost views)."""
    if repositories.get_device(device_id) is None:
        raise HTTPException(status_code=404, detail="frame not found")
    repositories.set_device_test(device_id, test)
    return {"device_id": device_id, "is_test": test}


@router.post("/accounts/{account_id}/test")
async def set_account_test(account_id: str, test: bool = True) -> dict:
    """Flag/unflag an account as a dev/test account — every frame it owns is then
    treated as test traffic in the admin views."""
    if repositories.get_account(account_id) is None:
        raise HTTPException(status_code=404, detail="account not found")
    repositories.set_account_test(account_id, test)
    return {"account_id": account_id, "is_test": test}


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
