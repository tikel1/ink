"""FastAPI entrypoint — wires routers, the PWA, and the scheduler."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import app_api, device_api, media_api
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
app.include_router(app_api.router)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


if STATIC_DIR.exists():
    app.mount("/app", StaticFiles(directory=STATIC_DIR, html=True), name="pwa")
