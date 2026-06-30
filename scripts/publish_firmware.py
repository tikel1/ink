#!/usr/bin/env python3
"""Publish a compiled frame firmware so the app can offer it as an OTA update.

Writes the built ESPHome app image + MD5 + manifest into the backend's hosting
dir (``data/firmware``). With ``--push`` it ALSO uploads to a remote backend
(e.g. Fly) over HTTPS via the admin endpoint, so a release reaches production
without filesystem access. Frames whose reported fw_version differs will see
"Update available" in the app and can pull this binary.

Usage:
    python scripts/publish_firmware.py <version> [path/to/firmware.bin]
    python scripts/publish_firmware.py <version> --push <base_url> --token <admin_token>

Examples:
    python scripts/publish_firmware.py 1.1.3
    python scripts/publish_firmware.py 1.1.3 --push https://ink-art-frame.fly.dev --token $ADMIN_TOKEN

The <version> MUST match the firmware's `fw_label` substitution so a freshly
flashed frame reads as already-up-to-date.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BIN = ROOT / "firmware/.esphome/build/ink-frame/.pioenvs/ink-frame/firmware.bin"
DEST_DIR = ROOT / "data/firmware"
BIN_NAME = "ink-frame.bin"


def _arg(argv: list[str], flag: str) -> str | None:
    return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else None


def _push(base_url: str, token: str, version: str, bin_path: Path, data: bytes) -> None:
    url = base_url.rstrip("/") + f"/api/app/admin/firmware?version={version}"
    headers = {"Content-Type": "application/octet-stream", "X-Admin-Token": token}
    try:
        req = urllib.request.Request(url, data=data, method="POST", headers=headers)
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 — fall back to curl (e.g. a stale Python CA bundle)
        import shutil as _sh
        import subprocess
        if not _sh.which("curl"):
            raise
        print(f"  (urllib failed: {exc}; retrying with curl)")
        body = subprocess.check_output([
            "curl", "-fsS", "-m", "120", "-X", "POST", "--data-binary", f"@{bin_path}",
            "-H", f"X-Admin-Token: {token}", "-H", "Content-Type: application/octet-stream", url,
        ]).decode("utf-8", "replace")
    print(f"  pushed -> {base_url}: {body}")


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    version = args[0].strip()
    # positional bin path (only if it isn't a flag value)
    push_url = _arg(argv, "--push")
    token = _arg(argv, "--token")
    bin_arg = args[1] if len(args) > 1 and args[1] not in (push_url, token) else None
    src = Path(bin_arg) if bin_arg else DEFAULT_BIN
    if not src.exists():
        print(f"error: firmware binary not found: {src}", file=sys.stderr)
        print("build it first: esphome compile firmware/trmnl-artframe.yaml", file=sys.stderr)
        return 1

    data = src.read_bytes()
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, DEST_DIR / BIN_NAME)
    md5 = hashlib.md5(data).hexdigest()
    (DEST_DIR / f"{BIN_NAME}.md5").write_text(md5, encoding="utf-8")
    manifest = {"version": version, "bin": BIN_NAME, "md5": md5, "size": len(data)}
    (DEST_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"published firmware v{version} locally")
    print(f"  bin:  {DEST_DIR / BIN_NAME}  ({len(data)} bytes)")
    print(f"  md5:  {md5}")

    if push_url:
        if not token:
            print("error: --push requires --token <admin_token>", file=sys.stderr)
            return 1
        try:
            _push(push_url, token, version, DEST_DIR / BIN_NAME, data)
        except Exception as exc:  # noqa: BLE001
            print(f"error: push failed: {exc}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
