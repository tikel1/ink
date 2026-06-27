"""Public URL paths for device images (joined onto PUBLIC_BASE_URL)."""
from __future__ import annotations


def current_url(device_id: str) -> str:
    return f"/media/current/{device_id}.png"


def archive_url(device_id: str, date: str) -> str:
    return f"/media/archive/{device_id}/{date}.png"
