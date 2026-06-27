"""Pure time helpers — no I/O, fully unit-testable.

Reproduces the original ESPHome 'sleep until wake_hour' logic
(trmnl.yaml:264-272) on the server side, so the device just sleeps for the
`refresh_rate` we hand it.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import constants


def seconds_until_next_wake(now: datetime, wake_hour: int) -> int:
    """Seconds from `now` until the next occurrence of `wake_hour:00` local.

    `now` must be timezone-aware. Result is clamped to [MIN, MAX] refresh
    bounds so a bad wake_hour can never produce a zero/negative sleep.
    """
    target = now.replace(hour=wake_hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    delta = int((target - now).total_seconds())
    return max(constants.MIN_REFRESH_SECONDS, min(constants.MAX_REFRESH_SECONDS, delta))


def now_in_tz(tz_name: str) -> datetime:
    return datetime.now(ZoneInfo(tz_name))


def local_date_str(tz_name: str) -> str:
    """Today's date (YYYY-MM-DD) in the device's timezone."""
    return now_in_tz(tz_name).strftime("%Y-%m-%d")
