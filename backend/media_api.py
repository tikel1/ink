"""Serve the bytes a device fetches: real artwork, or a splash by device state."""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import FileResponse, Response

from . import firmware_repo, generation, repositories, splash
from .config import get_settings

router = APIRouter(prefix="/media", tags=["media"])

PNG = "image/png"
AP_NAME = "Ink Frame"


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
        headers["X-Power"] = device.power_source            # usb | battery
        headers["X-Sleep"] = str(device.sleep_after_minutes)  # minutes awake before sleep
        headers["X-Wake"] = str(device.wake_hour)             # legacy: bare hour (old firmware)
        # Minute-precise wake as seconds-since-midnight (new firmware prefers this).
        headers["X-Wake-Secs"] = str(device.wake_hour * 3600 + device.wake_minute * 60)
        headers["X-Orient"] = device.orientation              # landscape | portrait
        ota_md5 = firmware_repo.latest_md5()                  # md5 of the published firmware
        if ota_md5:
            headers["X-OTA-Md5"] = ota_md5
    # One-shot command queued by the app (delivered once): 'refresh' | 'sleep'.
    cmd = repositories.take_pending_command(device_id)
    if cmd:
        headers["X-Cmd"] = cmd
    return Response(content=ver, media_type="text/plain", headers=headers)


@router.get("/sleep/{device_id}")
async def report_sleep(device_id: str) -> Response:
    """The frame hits this just before deep sleep so the app reflects 'Asleep'
    immediately. Cleared on the next check-in (.ver/.png)."""
    repositories.mark_sleeping(device_id)
    return Response(content="ok", media_type="text/plain")


@router.get("/ota-result/{device_id}")
async def report_ota_result(device_id: str, code: int = 0) -> Response:
    """The frame reports an OTA failure here (code != 0). Success isn't reported —
    the frame reboots into the new image and the app sees the version advance."""
    repositories.set_ota_result(device_id, str(code))
    return Response(content="ok", media_type="text/plain")


@router.get("/archive/{device_id}/{date}.png")
async def archive(device_id: str, date: str) -> Response:
    path = generation.archive_image_path(device_id, date)
    if path.exists():
        return FileResponse(path, media_type=PNG)
    return Response(status_code=404)
