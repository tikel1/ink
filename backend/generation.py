"""Bridge between a device row and the provider-agnostic pipeline.

Resolves whose key to use, runs the pipeline, and persists the image + metadata.
"""
from __future__ import annotations

import logging

from artframe.pipeline.generate import generate_artwork
from artframe.pipeline.imaging import save_image

from . import artwork_repo, keys, repositories
from .artwork_repo import READY, DailyArtwork
from .config import get_settings
from .keys import KeyUnavailableError
from .models import Device

logger = logging.getLogger(__name__)


def _safe(device_id: str) -> str:
    """Filesystem-safe stem for a device id (MACs may contain ':')."""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in device_id)


def current_image_path(device_id: str):
    return get_settings().images_dir / f"{_safe(device_id)}.png"


def archive_image_path(device_id: str, date: str):
    return get_settings().archive_dir / _safe(device_id) / f"{date}.png"


async def generate_for_device(device: Device) -> bool:
    """Generate today's artwork for a paired device. Returns success."""
    if not device.account_id:
        logger.info("skip %s: not paired to an account", device.id)
        return False
    account = repositories.get_account(device.account_id)
    if account is None:
        return False

    try:
        settings = keys.resolve_settings(account)
        result = await generate_artwork(settings, device.to_pipeline_config())
    except KeyUnavailableError as exc:
        # Expected when an account must supply its own key but hasn't yet.
        logger.warning("no key for %s: %s", device.id, exc)
        return False
    except Exception:  # noqa: BLE001 — never let one device crash the run.
        # Keep the last good image live rather than recording a junk row.
        logger.exception("generation failed for %s", device.id)
        return False

    save_image(result.image_png, current_image_path(device.id))
    save_image(result.image_png, archive_image_path(device.id, result.date))
    artwork_repo.upsert(
        DailyArtwork(
            device_id=device.id,
            date=result.date,
            image_path=str(current_image_path(device.id)),
            archive_path=str(archive_image_path(device.id, result.date)),
            event_text_en=result.event_text_en,
            event_text_he=result.event_text_he,
            weather_summary=result.weather_summary,
            orientation=device.orientation,
            status=READY,
            created_at=artwork_repo.make_now(),
        )
    )
    return True
