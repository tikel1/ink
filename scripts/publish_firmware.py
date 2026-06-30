#!/usr/bin/env python3
"""Publish a compiled frame firmware so the app can offer it as an OTA update.

Copies the built ESPHome app image into the backend's hosting dir, writes its
MD5 (ESPHome's http_request OTA verifies against it), and stamps a manifest with
the version string. Frames whose reported fw_version differs will see "Update
available" in the app and can pull this binary.

Usage:
    python scripts/publish_firmware.py <version> [path/to/firmware.bin]

Example:
    python scripts/publish_firmware.py 1.1.0

The <version> MUST match the firmware's `fw_label` substitution for the freshly
flashed frame to read as already-up-to-date.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BIN = ROOT / "firmware/.esphome/build/ink-frame/.pioenvs/ink-frame/firmware.bin"
DEST_DIR = ROOT / "data/firmware"
BIN_NAME = "ink-frame.bin"


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    version = argv[1].strip()
    src = Path(argv[2]) if len(argv) > 2 else DEFAULT_BIN
    if not src.exists():
        print(f"error: firmware binary not found: {src}", file=sys.stderr)
        print("build it first: esphome compile firmware/trmnl-artframe.yaml", file=sys.stderr)
        return 1

    DEST_DIR.mkdir(parents=True, exist_ok=True)
    dest_bin = DEST_DIR / BIN_NAME
    shutil.copyfile(src, dest_bin)

    md5 = hashlib.md5(dest_bin.read_bytes()).hexdigest()
    (DEST_DIR / f"{BIN_NAME}.md5").write_text(md5, encoding="utf-8")

    manifest = {"version": version, "bin": BIN_NAME, "md5": md5,
                "size": dest_bin.stat().st_size}
    (DEST_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"published firmware v{version}")
    print(f"  bin:  {dest_bin}  ({manifest['size']} bytes)")
    print(f"  md5:  {md5}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
