"""Firmware OTA hosting.

The backend keeps the latest frame firmware under ``data/firmware``:

  manifest.json        {"version": "1.1.0", "bin": "ink-frame.bin", "md5": "<hex>"}
  ink-frame.bin        the compiled app image the frame pulls + flashes
  ink-frame.bin.md5    its MD5 (ESPHome's http_request OTA verifies against this)

Publish a new build with ``scripts/publish_firmware.py``. The app compares the
manifest version against each device's reported ``fw_version`` to offer updates;
the frame pulls the binary itself (it can't be pushed to from a browser, and a
cloud backend can't reach the frame's LAN)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .config import get_settings

BIN_NAME = "ink-frame.bin"
MANIFEST_NAME = "manifest.json"


def _dir() -> Path:
    return get_settings().firmware_dir


def manifest_path() -> Path:
    return _dir() / MANIFEST_NAME


def bin_path() -> Path:
    return _dir() / BIN_NAME


def md5_path() -> Path:
    return _dir() / f"{BIN_NAME}.md5"


def read_manifest() -> Optional[dict]:
    """Return the published manifest, or None if no firmware has been published."""
    path = manifest_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict) or not data.get("version"):
        return None
    return data


def latest_version() -> Optional[str]:
    manifest = read_manifest()
    return manifest.get("version") if manifest else None


def latest_md5() -> Optional[str]:
    """MD5 of the published binary — sent to the frame so it can verify the OTA
    without a separate md5-URL fetch."""
    manifest = read_manifest()
    return manifest.get("md5") if manifest else None


def update_available(running_version: Optional[str]) -> bool:
    """True when a published firmware differs from what the device reports.

    Conservative: no manifest, or no reported version yet -> no update offered
    (we never nag a frame we can't compare)."""
    latest = latest_version()
    if not latest or not running_version:
        return False
    return latest != running_version
