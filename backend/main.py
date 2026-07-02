"""FastAPI entrypoint — wires routers, the PWA, and the scheduler."""
from __future__ import annotations

import logging
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from . import admin_api, app_api, device_api, firmware_api, media_api, monitoring_repo
from .config import get_settings
from .db import init_db
from .scheduler import create_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_db()
    scheduler = None
    if settings.enable_scheduler:
        scheduler = create_scheduler()
        scheduler.start()
        logger.info("scheduler started")
    try:
        yield
    finally:
        if scheduler:
            scheduler.shutdown(wait=False)


app = FastAPI(title="Ink", lifespan=lifespan)

# Allow the app to be hosted on a different origin (e.g. GitHub Pages) and still
# call this API. Auth is via bearer token in a header (not cookies), so a wide
# origin policy is safe here.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(device_api.router)
app.include_router(media_api.router)
app.include_router(firmware_api.router)
app.include_router(app_api.router)
app.include_router(admin_api.router)


# --------------------------------------------------------------------------- #
# API-call logging (feeds the admin monitoring console).
# --------------------------------------------------------------------------- #
_DEVICE_IN_PATH = re.compile(r"/(?:current|sleep|awake|ota-result|archive)/([^/.]+)")
_DEVICE_IN_APP = re.compile(r"/devices/([^/]+)")


def _classify(path: str) -> tuple[bool, str, str | None]:
    """(should_log, kind, device_id). We log the device + control-app + firmware
    traffic, but not the admin console's own polling or static asset serving."""
    if path.startswith("/api/admin"):
        return False, "admin", None
    if path.startswith("/api/app"):
        kind = "app"
    elif path.startswith("/media"):
        kind = "media"
    elif path.startswith("/firmware"):
        kind = "firmware"
    elif path.startswith("/api"):
        kind = "api"
    else:
        return False, "other", None          # static assets, /healthz, /app/*
    m = _DEVICE_IN_PATH.search(path) or _DEVICE_IN_APP.search(path)
    return True, kind, (m.group(1) if m else None)


@app.middleware("http")
async def log_api_calls(request: Request, call_next):
    start = time.monotonic()
    response = await call_next(request)
    try:
        should_log, kind, device_id = _classify(request.url.path)
        if should_log:
            monitoring_repo.record_api_call(
                request.method, request.url.path, kind, device_id,
                response.status_code, int((time.monotonic() - start) * 1000),
            )
    except Exception:  # noqa: BLE001 — logging must never break a request.
        logger.debug("api-call logging failed", exc_info=True)
    return response


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


# --------------------------------------------------------------------------- #
# Admin console — served OUTSIDE the PWA's /app service-worker scope and with
# no-store, so it can't be intercepted by a stale service worker or HTTP cache.
# --------------------------------------------------------------------------- #
_NO_STORE = {"Cache-Control": "no-store, must-revalidate"}


@app.get("/admin", include_in_schema=False)
async def admin_page():
    return HTMLResponse((STATIC_DIR / "admin.html").read_text(encoding="utf-8"), headers=_NO_STORE)


@app.get("/admin.js", include_in_schema=False)
async def admin_script():
    return Response((STATIC_DIR / "admin.js").read_text(encoding="utf-8"),
                    media_type="application/javascript", headers=_NO_STORE)


if STATIC_DIR.exists():
    app.mount("/app", StaticFiles(directory=STATIC_DIR, html=True), name="pwa")
