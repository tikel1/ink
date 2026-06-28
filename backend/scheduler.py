"""In-process daily generation scheduler.

A tick every few minutes generates for any paired+enabled device that has
entered its pre-wake window and has no ready image for today. Robust to
timezone / wake-hour edits made in the app.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from artframe.timeutil import now_in_tz

from . import artwork_repo, repositories
from .config import get_settings
from .generation import generate_for_device

logger = logging.getLogger(__name__)
TICK_MINUTES = 5


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_due_generations, trigger="interval", minutes=TICK_MINUTES,
        id="daily_tick", max_instances=1, coalesce=True,
    )
    return scheduler


async def run_due_generations() -> None:
    lead = get_settings().generation_lead_minutes
    for device in repositories.list_enabled_paired_devices():
        try:
            if _is_due(device, lead):
                logger.info("generating for %s", device.id)
                await generate_for_device(device)
        except Exception:  # noqa: BLE001
            logger.exception("scheduler tick failed for %s", device.id)


def _is_due(device, lead_minutes: int) -> bool:
    now = now_in_tz(device.tz)
    if not _scheduled_today(device, now):
        return False
    existing = artwork_repo.get(device.id, now.date().isoformat())
    if existing and existing.status == artwork_repo.READY:
        return False
    wake = now.replace(hour=device.wake_hour, minute=0, second=0, microsecond=0)
    return wake - timedelta(minutes=lead_minutes) <= now < wake


def _scheduled_today(device, now) -> bool:
    """daily → every day; weekly/custom → only on the chosen weekday(s)."""
    if device.schedule == "daily":
        return True
    days = {d.strip().lower() for d in (device.schedule_days or "").split(",") if d.strip()}
    if not days:                       # nothing chosen → don't strand the frame
        return True
    return now.strftime("%a").lower() in days
