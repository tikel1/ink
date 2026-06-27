"""In-memory generation-job status, keyed by device id.

At this scale (1-10 accounts, a single backend process) an in-memory map is
enough — the app polls it to show progress and reveal the new image. State is
transient by design: a restart just resets everyone to 'idle'.
"""
from __future__ import annotations

_jobs: dict[str, dict[str, str]] = {}

IDLE = "idle"
RUNNING = "running"
DONE = "done"
ERROR = "error"


def set_state(device_id: str, state: str, detail: str = "") -> None:
    _jobs[device_id] = {"state": state, "detail": detail}


def get(device_id: str) -> dict[str, str]:
    return _jobs.get(device_id, {"state": IDLE, "detail": ""})
