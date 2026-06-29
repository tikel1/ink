"""BYOS device-facing API — matches the stock TRMNL firmware contract.

The device is identified by its hardware id (ID header). One backend base URL
serves every device; account binding happens later via a pairing code, so the
firmware never needs a per-device URL.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from artframe.timeutil import now_in_tz, seconds_until_next_wake

from . import artwork_repo, repositories, storage
from .config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["device"])

RETRY_SECONDS = 300  # short cadence while unpaired or awaiting first image
STATUS_PAIRED = "paired"


def _abs(rel: str) -> str:
    return get_settings().public_base_url.rstrip("/") + rel


def _f(v):
    try:
        return float(v) if v is not None else None
    except ValueError:
        return None


def _i(v):
    try:
        return int(float(v)) if v is not None else None
    except ValueError:
        return None


@router.get("/setup")
async def setup(id: str | None = Header(default=None)):
    if not id:
        return JSONResponse({"status": 400, "message": "missing ID header"}, 400)
    device = repositories.register_device(id)
    return {
        "status": 200,
        "api_key": device.api_key,
        "friendly_id": device.id,
        "image_url": _abs(storage.current_url(device.id)),
        "message": "Add this frame in the Ink app",
    }


@router.get("/display")
async def display(
    request: Request,
    id: str | None = Header(default=None),
    access_token: str | None = Header(default=None, alias="Access-Token"),
):
    if not id:
        return JSONResponse({"status": 400, "message": "missing ID header"}, 400)

    device = repositories.register_device(id)
    repositories.update_telemetry(
        device.id,
        battery=_f(request.headers.get("battery-voltage")),
        wifi_rssi=_i(request.headers.get("rssi")),
        fw_version=request.headers.get("fw-version"),
    )

    if device.status != STATUS_PAIRED:
        return _resp(storage.current_url(device.id), RETRY_SECONDS, "pairing")

    today = now_in_tz(device.tz).date().isoformat()
    art = artwork_repo.get(device.id, today)
    if art and art.status == artwork_repo.READY:
        refresh = seconds_until_next_wake(now_in_tz(device.tz), device.wake_hour, device.wake_minute)
        return _resp(storage.current_url(device.id), refresh, art.date)
    return _resp(storage.current_url(device.id), RETRY_SECONDS, "pending")


@router.get("/log")
async def log_sink(request: Request, id: str | None = Header(default=None)):
    logger.info("device %s log: %s", id, dict(request.query_params))
    return {"status": 200}


def _resp(rel_url: str, refresh: int, filename: str) -> dict:
    return {
        "status": 200,
        "image_url": _abs(rel_url),
        "filename": filename,
        "refresh_rate": refresh,
        "reset_firmware": False,
        "update_firmware": False,
        "firmware_url": None,
        "special_function": "none",
    }
