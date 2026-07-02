"""Bridge between a device row and the provider-agnostic pipeline.

Resolves whose key to use, runs the pipeline, and persists the image + metadata.
"""
from __future__ import annotations

import json
import logging
import time

from artframe.pipeline import metrics as gen_metrics
from artframe.pipeline.generate import generate_artwork
from artframe.pipeline.imaging import save_image

from . import artwork_repo, costs, keys, monitoring_repo, repositories
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


def archive_original_path(device_id: str, date: str):
    """Full-detail original (grayscale JPEG) for app zoom / admin preview."""
    return get_settings().archive_dir / _safe(device_id) / f"{date}.orig.jpg"


_KEEP_ORIGINALS = 120   # most-recent originals kept per device (~25 MB); panel PNGs stay forever


def _prune_originals(device_id: str) -> None:
    """Bound the Fly volume: originals are ~10x a panel PNG, so keep only the
    newest _KEEP_ORIGINALS per device (zoom falls back to the panel for older)."""
    folder = get_settings().archive_dir / _safe(device_id)
    try:
        originals = sorted(folder.glob("*.orig.jpg"))
        for stale in originals[:-_KEEP_ORIGINALS]:
            stale.unlink(missing_ok=True)
    except OSError:
        logger.warning("could not prune originals for %s", device_id, exc_info=True)


async def generate_for_device(device: Device, on_phase=None, trigger: str = "manual") -> bool:
    """Generate today's artwork for a paired device. Returns success.

    `on_phase(name)` is forwarded to the pipeline so the app can show real
    per-stage progress on the Generate button. Every attempt (success or failure)
    is recorded in generation_runs with duration, cost estimate, retries, the last
    phase reached, and any error — the data behind the admin monitoring console.
    """
    if not device.account_id:
        logger.info("skip %s: not paired to an account", device.id)
        return False
    account = repositories.get_account(device.account_id)
    if account is None:
        return False

    metric = gen_metrics.start()
    last_phase = {"name": ""}

    def _phase(name: str) -> None:
        last_phase["name"] = name
        if on_phase:
            on_phase(name)

    started = time.monotonic()
    ok, error, date_str, quality = False, "", "", "medium"
    try:
        settings = keys.resolve_settings(account)
        quality = getattr(settings, "openai_image_quality", "medium")
        result = await generate_artwork(settings, device.to_pipeline_config(), on_phase=_phase)
        save_image(result.image_png, current_image_path(device.id))
        save_image(result.image_png, archive_image_path(device.id, result.date))
        if result.original_jpg:
            save_image(result.original_jpg, archive_original_path(device.id, result.date))
            _prune_originals(device.id)
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
                image_prompt=result.image_prompt,
                event_caption=result.event_caption,
                event_visual=result.event_visual,
                other_events=json.dumps(list(result.other_events)) if result.other_events else None,
                status=READY,
                created_at=artwork_repo.make_now(),
            )
        )
        date_str = result.date
        # Guarantee the physical frame shows the new art: queue a refresh the device
        # picks up on its next poll. (The version stamp also bumps; the firmware
        # redraws at most once per poll, so this never double-flashes the e-ink.)
        repositories.set_pending_command(device.id, "refresh")
        ok = True
    except KeyUnavailableError as exc:
        # Expected when an account must supply its own key but hasn't yet.
        error = f"no API key: {exc}"
        logger.warning("no key for %s: %s", device.id, exc)
    except Exception as exc:  # noqa: BLE001 — never let one device crash the run.
        # Keep the last good image live rather than recording a junk artwork row.
        error = f"{type(exc).__name__}: {exc}"[:300]
        logger.exception("generation failed for %s", device.id)
    finally:
        _record_run(device, trigger, ok, error, date_str, quality,
                    "" if ok else last_phase["name"],
                    int((time.monotonic() - started) * 1000), metric)
    return ok


def _record_run(device, trigger, ok, error, date_str, quality, phase, duration_ms, metric) -> None:
    m = metric or gen_metrics.GenMetrics()
    cost = costs.estimate(quality, m.image_calls, m.text_calls, m.search_calls, m.text_tokens)
    try:
        monitoring_repo.record_generation_run(
            device_id=device.id, account_id=device.account_id, date=date_str,
            trigger=trigger, ok=1 if ok else 0, duration_ms=duration_ms,
            retries=m.retries, image_calls=m.image_calls, text_calls=m.text_calls,
            search_calls=m.search_calls, text_tokens=m.text_tokens, cost_usd=cost,
            provider=m.provider_str(), phase=phase, error=error,
        )
    except Exception:  # noqa: BLE001 — monitoring must never break generation.
        logger.exception("failed to record generation run for %s", device.id)
