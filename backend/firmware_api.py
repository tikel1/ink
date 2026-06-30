"""Serves the OTA firmware binary + checksum the frames pull on an 'ota' command.

Unauthenticated like the media endpoints (frames identify by MAC, carry no
secret) — the binary isn't sensitive. Filenames are fixed, so there is no
path-traversal surface."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

from . import firmware_repo

router = APIRouter(prefix="/firmware", tags=["firmware"])

_OCTET = "application/octet-stream"


@router.get("/ink-frame.bin")
async def firmware_bin() -> Response:
    path = firmware_repo.bin_path()
    if not path.exists():
        raise HTTPException(status_code=404, detail="no firmware published")
    return FileResponse(path, media_type=_OCTET, filename=firmware_repo.BIN_NAME)


@router.get("/ink-frame.bin.md5")
async def firmware_md5() -> Response:
    path = firmware_repo.md5_path()
    if not path.exists():
        raise HTTPException(status_code=404, detail="no firmware published")
    # Plain-text 32-char hex; ESPHome's http_request OTA reads it from md5_url.
    return Response(content=path.read_text(encoding="utf-8").strip(),
                    media_type="text/plain")


@router.get("/manifest.json")
async def firmware_manifest() -> Response:
    manifest = firmware_repo.read_manifest()
    if manifest is None:
        raise HTTPException(status_code=404, detail="no firmware published")
    return manifest
