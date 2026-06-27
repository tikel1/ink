"""Serve the bytes a device fetches: real artwork, or a splash by device state."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import FileResponse, Response

from . import generation, repositories, splash
from .config import get_settings

router = APIRouter(prefix="/media", tags=["media"])

PNG = "image/png"
AP_NAME = "Ink Frame"


def _png(data: bytes) -> Response:
    return Response(content=data, media_type=PNG)


def _pair_url(code: str) -> str:
    base = get_settings().public_base_url.rstrip("/")
    return f"{base}/app/?code={code}"


@router.get("/current/{device_id}.png")
async def current(device_id: str) -> Response:
    # First fetch from a new frame auto-registers it (idempotent), so it gets a
    # pairing code without a separate setup call.
    device = repositories.register_device(device_id)
    if device.status != "paired":
        code = device.pairing_code or ""
        return _png(splash.pairing_splash(code, _pair_url(code)))

    path = generation.current_image_path(device_id)
    if path.exists():
        return FileResponse(path, media_type=PNG)
    return _png(splash.connect_splash(AP_NAME))


@router.get("/archive/{device_id}/{date}.png")
async def archive(device_id: str, date: str) -> Response:
    path = generation.archive_image_path(device_id, date)
    if path.exists():
        return FileResponse(path, media_type=PNG)
    return Response(status_code=404)
