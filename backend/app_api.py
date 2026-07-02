"""Control-app API: accounts, API-key management, device pairing + preferences."""
from __future__ import annotations

import json
import secrets
import time
from collections import deque

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from pydantic import BaseModel, Field

from . import artwork_repo, auth, crypto, firmware_repo, generation, jobs, keys, repositories, storage
from .config import get_settings
from .generation import generate_for_device
from .models import Account, Device

router = APIRouter(prefix="/api/app", tags=["app"])

WAKE_MIN, WAKE_MAX = 0, 23


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
class PairRequest(BaseModel):
    pairing_code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class KeyRequest(BaseModel):
    openai_api_key: str = Field(min_length=10, max_length=300)


class ConfigUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=40)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    tz: str | None = None
    wake_hour: int | None = Field(default=None, ge=WAKE_MIN, le=WAKE_MAX)
    wake_minute: int | None = Field(default=None, ge=0, le=59)
    language: str | None = Field(default=None, pattern=r"^(en|he)$")
    temp_unit: str | None = Field(default=None, pattern=r"^(c|f)$")
    interests: str | None = None
    signature: str | None = None
    holiday_jewish: bool | None = None
    holiday_israeli: bool | None = None
    holiday_global: bool | None = None
    orientation: str | None = Field(default=None, pattern=r"^(landscape|portrait)$")
    show_date: bool | None = None
    # Token format string (ddd/dddd/MMM/MMMM/MM/D/Do/DD/YYYY/YY + separators) or a
    # legacy enum key. Constrained charset/length; the renderer treats unknown
    # letters as literals so a custom string can't break generation.
    date_format: str | None = Field(default=None, min_length=1, max_length=40, pattern=r"^[A-Za-z0-9 ,/.'\-]+$")
    show_weather: bool | None = None
    use_weather: bool | None = None
    use_event: bool | None = None
    city_name: str | None = Field(default=None, max_length=80)
    auto_timezone: bool | None = None
    schedule: str | None = Field(default=None, pattern=r"^(daily|weekly|custom)$")
    schedule_days: str | None = Field(default=None, max_length=60)
    # Single sleep policy: 0 = always on, >0 = sleep after N minutes of uptime.
    # (The frame can't sense its own power, so there's no plugged/battery split.)
    sleep_after_minutes: int | None = Field(default=None, ge=0, le=240)
    custom_prompt_override: str | None = None
    enabled: bool | None = None


# --------------------------------------------------------------------------- #
# Accounts + keys
# --------------------------------------------------------------------------- #
# Light in-memory throttle on anonymous account minting (an open endpoint by
# design — the app's "Get started"). Bounds DB-bloat/token-farming without a new
# dependency; per-process is fine on the single Fly machine.
_MINT_WINDOW_S = 3600
_MINT_MAX_PER_WINDOW = 20
_mint_times: deque[float] = deque()


@router.post("/account")
async def create_account():
    now = time.monotonic()
    while _mint_times and now - _mint_times[0] > _MINT_WINDOW_S:
        _mint_times.popleft()
    if len(_mint_times) >= _MINT_MAX_PER_WINDOW:
        raise HTTPException(status_code=429,
                            detail="Too many new accounts right now — try again later.")
    _mint_times.append(now)
    account, token = auth.create_account()
    return {"account_id": account.id, "token": token}


@router.get("/account")
async def get_account(account: Account = auth.AccountDep):
    state = keys.key_state(account)
    return {"account_id": account.id, "key_status": state.status,
            "has_own_key": state.has_own_key}


@router.put("/account/key")
async def set_key(body: KeyRequest, account: Account = auth.AccountDep):
    repositories.set_account_key(account.id, crypto.encrypt(body.openai_api_key))
    return {"key_status": keys.STATUS_OWN}


@router.delete("/account/key")
async def clear_key(account: Account = auth.AccountDep):
    if account.key_required:
        raise HTTPException(status_code=409, detail="your own key is required")
    repositories.set_account_key(account.id, None)
    return {"key_status": keys.STATUS_PLATFORM}


# --------------------------------------------------------------------------- #
# Devices
# --------------------------------------------------------------------------- #
@router.get("/devices")
async def list_devices(account: Account = auth.AccountDep):
    return {"devices": [_device_payload(d) for d in
                        repositories.list_account_devices(account.id)]}


@router.post("/devices/pair")
async def pair(body: PairRequest, account: Account = auth.AccountDep):
    device = repositories.get_device_by_pairing_code(body.pairing_code)
    if device is None:
        raise HTTPException(status_code=404, detail="invalid pairing code")
    repositories.bind_device(device.id, account.id)
    # No auto-generation: the frame keeps showing its last image, or a "Pairing
    # successful — tap Generate" splash if it has none. The user generates the
    # first artwork explicitly.
    return _device_payload(_owned(device.id, account))


class ReorderRequest(BaseModel):
    order: list[str] = Field(min_length=1, max_length=100)


@router.post("/devices/reorder")
async def reorder(body: ReorderRequest, account: Account = auth.AccountDep):
    """Persist the home-carousel order. Every id must belong to the account."""
    owned = {d.id for d in repositories.list_account_devices(account.id)}
    if not set(body.order).issubset(owned):
        raise HTTPException(status_code=404, detail="unknown device in order")
    repositories.set_device_order(account.id, body.order)
    return {"status": "ok"}


@router.get("/devices/{device_id}")
async def get_device(device_id: str, account: Account = auth.AccountDep):
    return _device_payload(_owned(device_id, account))


@router.put("/devices/{device_id}/config")
async def update_config(device_id: str, body: ConfigUpdate,
                        account: Account = auth.AccountDep):
    _owned(device_id, account)
    repositories.update_device_config(device_id, **body.model_dump(exclude_none=True))
    return _device_payload(_owned(device_id, account))


@router.get("/devices/{device_id}/archive")
async def archive(device_id: str, limit: int = 30, account: Account = auth.AccountDep):
    _owned(device_id, account)
    items = artwork_repo.list_archive(device_id, limit=limit)
    return {"items": [{
        "date": a.date,
        "image_url": storage.archive_url(device_id, a.date),
        # Full-detail original for the zoom view; None for older artworks whose
        # original was pruned (zoom then falls back to the panel image).
        "image_full_url": (storage.archive_original_url(device_id, a.date)
                           if generation.archive_original_path(device_id, a.date).exists()
                           else None),
        "event_text_en": a.event_text_en,
        "event_text_he": a.event_text_he,
        "weather_summary": a.weather_summary,
        "orientation": a.orientation,
        "other_events": _parse_other_events(a.other_events),
    } for a in items]}


def _parse_other_events(raw: str | None) -> list:
    """Date-verified runner-up events stored as JSON; tolerate legacy/empty rows."""
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except (ValueError, TypeError):
        return []


# Manual regenerations are the one user action that spends real money. Cap them
# per device per day (resets at local midnight with the date key) — generous for
# real use, a wall against a stuck finger / a leaked token.
_REGEN_DAILY_CAP = 20
_regen_counts: dict[str, tuple[str, int]] = {}   # device_id -> (date, count)


def _regen_allowed(device: Device) -> bool:
    from artframe.timeutil import now_in_tz
    today = now_in_tz(device.tz).date().isoformat()
    date_key, count = _regen_counts.get(device.id, (today, 0))
    if date_key != today:
        count = 0
    if count >= _REGEN_DAILY_CAP:
        return False
    _regen_counts[device.id] = (today, count + 1)
    return True


@router.post("/devices/{device_id}/regenerate")
async def regenerate(device_id: str, background: BackgroundTasks,
                     account: Account = auth.AccountDep):
    device = _owned(device_id, account)
    # One at a time: racing a second generation would double the image cost and
    # the two would fight over the same output file.
    if jobs.get(device.id).get("state") == jobs.RUNNING:
        raise HTTPException(status_code=409, detail="Already creating — hang on.")
    if not _regen_allowed(device):
        raise HTTPException(status_code=429,
                            detail="Daily generation limit reached — try again tomorrow.")
    jobs.set_state(device.id, jobs.RUNNING)
    background.add_task(_run_generation, device)
    return {"status": jobs.RUNNING,
            "note": "Creating today's art…"}


@router.get("/devices/{device_id}/generation")
async def generation_status(device_id: str, account: Account = auth.AccountDep):
    _owned(device_id, account)
    return jobs.get(device_id)


async def _run_generation(device: Device) -> None:
    try:
        # Report each pipeline stage as the job's detail so the app's Generate
        # button reflects real progress (discover → research → compose → paint → finish).
        ok = await generate_for_device(
            device, on_phase=lambda p: jobs.set_state(device.id, jobs.RUNNING, p)
        )
        jobs.set_state(
            device.id,
            jobs.DONE if ok else jobs.ERROR,
            "" if ok else "Couldn't generate — check the API key and try again.",
        )
    except Exception:  # noqa: BLE001
        jobs.set_state(device.id, jobs.ERROR, "Generation failed — try again.")


class CommandRequest(BaseModel):
    cmd: str = Field(pattern=r"^(refresh|sleep|ota|reset)$")


@router.post("/devices/{device_id}/command")
async def send_command(device_id: str, body: CommandRequest,
                       account: Account = auth.AccountDep):
    """Queue a one-shot command the physical frame picks up on its next poll
    (≤60s): 'refresh' = re-fetch + redraw now, 'sleep' = go to sleep,
    'ota' = pull + flash the latest firmware, 'reset' = factory wipe."""
    _owned(device_id, account)
    if body.cmd == "ota":
        repositories.clear_ota_result(device_id)   # fresh attempt — drop any stale failure
    repositories.set_pending_command(device_id, body.cmd)
    # Factory restore is a full wipe + unpair: the frame clears its Wi-Fi/account
    # on the 'reset' command, and we forget it server-side so it returns to QR
    # onboarding. (The pending command is still delivered — take_pending_command
    # runs regardless of pairing — so order doesn't matter.)
    if body.cmd == "reset":
        repositories.unbind_device(device_id)
    return {"status": "queued", "cmd": body.cmd}


@router.post("/devices/{device_id}/unbind")
async def unbind(device_id: str, account: Account = auth.AccountDep):
    _owned(device_id, account)
    repositories.unbind_device(device_id)
    return {"status": "unbound"}


# --------------------------------------------------------------------------- #
# Admin (flip own-key-required remotely)
# --------------------------------------------------------------------------- #
def _check_admin(x_admin_token: str | None) -> None:
    """Constant-time admin-token check (a plain != leaks timing information)."""
    admin = getattr(get_settings(), "admin_token", "")
    if not admin or not secrets.compare_digest(x_admin_token or "", admin):
        raise HTTPException(status_code=403, detail="admin only")


@router.post("/admin/accounts/{account_id}/require-own-key")
async def require_own_key(account_id: str, required: bool = True,
                          x_admin_token: str | None = Header(default=None)):
    _check_admin(x_admin_token)
    if repositories.get_account(account_id) is None:
        raise HTTPException(status_code=404, detail="account not found")
    repositories.set_key_required(account_id, required)
    return {"account_id": account_id, "key_required": required}


@router.post("/admin/firmware")
async def publish_firmware(version: str, request: Request,
                           x_admin_token: str | None = Header(default=None)):
    """Publish an OTA firmware build to this backend's storage. Admin-token
    gated (disabled when ADMIN_TOKEN is unset). Body = the raw .bin; the md5 is
    computed server-side. Lets us push releases to a remote (e.g. Fly) over
    HTTPS without filesystem access."""
    _check_admin(x_admin_token)
    if not version or len(version) > 32:
        raise HTTPException(status_code=400, detail="bad version")
    data = await request.body()
    if len(data) < 1024:
        raise HTTPException(status_code=400, detail="firmware too small / empty")
    return firmware_repo.write_firmware(version, data)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _owned(device_id: str, account: Account) -> Device:
    device = repositories.get_device(device_id)
    if device is None or device.account_id != account.id:
        raise HTTPException(status_code=404, detail="device not found")
    return device


def _device_payload(device: Device) -> dict:
    today_status = None
    return {
        "id": device.id,
        "status": device.status,
        "name": device.name,
        "tz": device.tz,
        "lat": device.lat,
        "lon": device.lon,
        "wake_hour": device.wake_hour,
        "wake_minute": device.wake_minute,
        "language": device.language,
        "temp_unit": device.temp_unit,
        "interests": device.interests,
        "signature": device.signature,
        "holiday_jewish": device.holiday_jewish,
        "holiday_israeli": device.holiday_israeli,
        "holiday_global": device.holiday_global,
        "orientation": device.orientation,
        "show_date": device.show_date,
        "date_format": device.date_format,
        "show_weather": device.show_weather,
        "use_weather": device.use_weather,
        "use_event": device.use_event,
        "city_name": device.city_name,
        "auto_timezone": device.auto_timezone,
        "schedule": device.schedule,
        "schedule_days": device.schedule_days,
        "sleep_after_minutes": device.sleep_after_minutes,  # 0 = always on
        "sleeping": device.sleeping,
        "custom_prompt_override": device.custom_prompt_override,
        "enabled": device.enabled,
        "battery": device.battery,
        "wifi_rssi": device.wifi_rssi,
        "last_seen": device.last_seen,
        "last_auto_gen": device.last_auto_gen,   # date (YYYY-MM-DD) the daily update last ran
        "fw_version": device.fw_version,
        "latest_fw": firmware_repo.latest_version(),
        "update_available": firmware_repo.update_available(device.fw_version),
        "ota_error": device.ota_error,
        "today_status": today_status,
    }
