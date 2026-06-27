"""Tests for the dynamic refresh-rate / sleep-until-wake logic."""
from datetime import datetime
from zoneinfo import ZoneInfo

from artframe import constants
from artframe.timeutil import seconds_until_next_wake

TZ = ZoneInfo("Asia/Jerusalem")


def test_sleep_until_morning_same_day():
    # 01:00, wake at 06:00 → 5 hours.
    now = datetime(2026, 6, 26, 1, 0, tzinfo=TZ)
    assert seconds_until_next_wake(now, 6) == 5 * 3600


def test_sleep_wraps_to_next_day():
    # 09:00, wake at 06:00 → 21 hours until tomorrow 06:00.
    now = datetime(2026, 6, 26, 9, 0, tzinfo=TZ)
    assert seconds_until_next_wake(now, 6) == 21 * 3600


def test_exactly_at_wake_hour_wraps_full_day():
    now = datetime(2026, 6, 26, 6, 0, tzinfo=TZ)
    assert seconds_until_next_wake(now, 6) == constants.SECONDS_PER_DAY


def test_clamped_to_minimum():
    # 05:59:30, wake 06:00 → 30s, clamped up to the minimum refresh.
    now = datetime(2026, 6, 26, 5, 59, 30, tzinfo=TZ)
    assert seconds_until_next_wake(now, 6) == constants.MIN_REFRESH_SECONDS
