"""Serve the bytes a device fetches: real artwork, or a splash by device state."""
from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import FileResponse, Response

from artframe.timeutil import now_in_tz

from . import firmware_repo, generation, jobs, repositories, splash
from .config import get_settings
from .scheduler import _is_due

router = APIRouter(prefix="/media", tags=["media"])
logger = logging.getLogger(__name__)

PNG = "image/png"
AP_NAME = "Ink Frame"


async def _run_frame_generation(device) -> None:
    """Generate for a frame that just checked in and is due. Marks the per-day
    'done' flag on success (so it fires once), and leaves the job state so the
    poll can tell the frame to stay awake while it runs."""
    try:
        ok = await generation.generate_for_device(
            device, on_phase=lambda p: jobs.set_state(device.id, jobs.RUNNING, p))
        jobs.set_state(device.id, jobs.DONE if ok else jobs.ERROR)
        if ok:
            repositories.mark_auto_generated(
                device.id, now_in_tz(device.tz).date().isoformat())
    except Exception:  # noqa: BLE001
        logger.exception("frame-driven generation failed for %s", device.id)
        jobs.set_state(device.id, jobs.ERROR)


# Strong references to in-flight generation tasks. asyncio only keeps a weak
# reference to tasks, so a fire-and-forget create_task can be garbage-collected
# mid-await — the generation would vanish silently with the job stuck RUNNING.
_gen_tasks: dict[str, asyncio.Task] = {}


def _maybe_start_generation(device) -> bool:
    """Frame-driven handshake: a paired frame that polls while its daily update is
    due kicks generation right then (proof it's awake + reachable). Deduped via the
    job state so repeated polls don't stack. Returns True while a job is running."""
    if jobs.get(device.id).get("state") == jobs.RUNNING:
        return True
    if not _is_due(device, get_settings().generation_lead_minutes):
        return False
    jobs.set_state(device.id, jobs.RUNNING)
    try:
        task = asyncio.create_task(_run_frame_generation(device))
    except RuntimeError:  # event loop shutting down — don't leave RUNNING stuck
        jobs.set_state(device.id, jobs.IDLE)
        return False
    _gen_tasks[device.id] = task
    task.add_done_callback(lambda _t, _id=device.id: _gen_tasks.pop(_id, None))
    logger.info("frame-driven generation started for %s", device.id)
    return True


def _png(data: bytes) -> Response:
    return Response(content=data, media_type=PNG)


def _pair_url(code: str) -> str:
    """Where the frame's QR sends the phone: the install/open app URL, carrying
    the backend address + pairing code so one scan installs/opens and pairs."""
    settings = get_settings()
    app = (settings.app_url or (settings.public_base_url.rstrip("/") + "/app")).rstrip("/")
    server = quote(settings.public_base_url.rstrip("/"), safe="")
    return f"{app}/?code={code}&server={server}"


@router.get("/current/{device_id}.png")
async def current(device_id: str) -> Response:
    # First fetch from a new frame auto-registers it (idempotent), so it gets a
    # pairing code without a separate setup call.
    device = repositories.register_device(device_id)
    # NOTE: do NOT treat an image fetch as a check-in. The control app also loads
    # this same .png (home/frame/gallery), so stamping last_seen here made the
    # frame look "Online" every time the app opened. Only the frame's .ver poll
    # (frame-only) counts as a check-in.
    if device.status != "paired":
        code = device.pairing_code or ""
        return _png(splash.pairing_splash(code, _pair_url(code)))

    path = generation.current_image_path(device_id)
    if path.exists():
        return FileResponse(path, media_type=PNG)
    return _png(splash.connect_splash(AP_NAME))


@router.get("/current/{device_id}.ver")
async def current_version(
    device_id: str,
    bat: float | None = None,
    rssi: int | None = None,
    fw: str | None = None,
) -> Response:
    """Tiny version stamp the frame polls so it re-fetches only when the artwork
    actually changed (avoids constant e-ink refreshes). Also counts as a check-in;
    the frame piggybacks its telemetry (battery V, Wi-Fi RSSI, firmware) as query
    params so the app can show them."""
    # Sanitize telemetry: drop absurd values (NaN/inf/garbage) instead of storing
    # them, but never reject the poll — the check-in itself must always land.
    if bat is not None and not (0.0 <= bat <= 10.0):
        bat = None
    if rssi is not None and not (-150 <= rssi <= 20):
        rssi = None
    if fw is not None and len(fw) > 32:
        fw = None
    repositories.update_telemetry(device_id, battery=bat, wifi_rssi=rssi, fw_version=fw)
    device = repositories.get_device(device_id)
    if device is not None and device.status != "paired":
        # Unpaired (e.g. just unbound from the app) -> a version distinct from the
        # stale artwork's, so the frame re-fetches .png and shows the pairing
        # splash instead of holding the last image. Stable while the code stands.
        ver = "pair-" + (device.pairing_code or "0")
    else:
        path = generation.current_image_path(device_id)
        ver = str(int(path.stat().st_mtime)) if path.exists() else "0"
    # Expose version + power/sleep config as response headers — the frame's
    # Arduino HTTP client reads collected headers reliably (the body does not).
    headers = {"X-Ver": ver}
    if device is not None:
        # Single user choice: sleep_after_minutes (0 = always on, >0 = sleep after N).
        # Map it to the headers both firmwares understand: current firmware only
        # sleeps when X-Power == "battery", so send "battery" whenever sleep is on
        # and "usb" for always-on. (New firmware honors X-Sleep > 0 directly.)
        sleep_min = device.sleep_after_minutes
        headers["X-Power"] = "battery" if sleep_min > 0 else "usb"
        headers["X-Sleep"] = str(sleep_min)                # minutes awake before sleep (0 = never)
        headers["X-Wake"] = str(device.wake_hour)             # legacy: bare hour (old firmware)
        # Minute-precise wake as seconds-since-midnight (new firmware prefers this).
        headers["X-Wake-Secs"] = str(device.wake_hour * 3600 + device.wake_minute * 60)
        headers["X-Orient"] = device.orientation              # landscape | portrait
        ota_md5 = firmware_repo.latest_md5()                  # md5 of the published firmware
        if ota_md5:
            headers["X-OTA-Md5"] = ota_md5
        # Frame-driven generation: if the daily update is due, this poll (proof the
        # frame is awake) kicks it. X-Gen=pending tells the frame to stay awake
        # until the new image lands, instead of sleeping mid-generation.
        if device.status == "paired" and _maybe_start_generation(device):
            headers["X-Gen"] = "pending"
    # One-shot command queued by the app (delivered once): 'refresh' | 'sleep'.
    cmd = repositories.take_pending_command(device_id)
    if cmd:
        headers["X-Cmd"] = cmd
    return Response(content=ver, media_type="text/plain", headers=headers)


@router.get("/sleep/{device_id}")
async def report_sleep(device_id: str) -> Response:
    """The frame hits this just before deep sleep so the app reflects 'Asleep'
    immediately. Cleared on the next check-in (.ver / wake report)."""
    repositories.mark_sleeping(device_id)
    return Response(content="ok", media_type="text/plain")


@router.get("/awake/{device_id}")
async def report_awake(device_id: str) -> Response:
    """The frame hits this the moment it wakes (boot, before the first .ver poll)
    so the app flips to 'Online' instantly instead of waiting for the next
    heartbeat. Stamps last_seen + clears the sleeping flag; unlike .ver it does
    NOT consume a queued command (the poll handles those)."""
    repositories.update_telemetry(device_id)
    return Response(content="ok", media_type="text/plain")


@router.get("/refreshed/{device_id}")
async def report_refreshed(device_id: str) -> Response:
    """The frame pings this once it has fetched + rendered the new image, closing
    the wake→generate→refresh handshake. We stamp the check-in and clear the job so
    the app shows 'updated' and the frame is free to fall back to its sleep timer."""
    repositories.update_telemetry(device_id)
    jobs.set_state(device_id, jobs.IDLE)
    return Response(content="ok", media_type="text/plain")


@router.get("/ota-result/{device_id}")
async def report_ota_result(device_id: str, code: int = 0) -> Response:
    """The frame reports an OTA failure here (code != 0). Success isn't reported —
    the frame reboots into the new image and the app sees the version advance."""
    repositories.set_ota_result(device_id, str(code))
    return Response(content="ok", media_type="text/plain")


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@router.get("/archive/{device_id}/{date}.png")
async def archive(device_id: str, date: str) -> Response:
    # Strict date shape — never let a crafted value reach the path builder.
    if not _DATE_RE.match(date):
        return Response(status_code=404)
    path = generation.archive_image_path(device_id, date)
    if path.exists():
        return FileResponse(path, media_type=PNG)
    return Response(status_code=404)


@router.get("/archive/{device_id}/{date}.orig.jpg")
async def archive_original(device_id: str, date: str) -> Response:
    """Full-detail original for app zoom / admin preview (kept for the newest
    ~120 generations per device; older fall back to the panel PNG)."""
    if not _DATE_RE.match(date):
        return Response(status_code=404)
    path = generation.archive_original_path(device_id, date)
    if path.exists():
        return FileResponse(path, media_type="image/jpeg")
    return Response(status_code=404)
