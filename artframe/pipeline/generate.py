"""Generate one device's daily artwork from its config.

1:1 port of the Home Assistant automation ordering: weather → event → image →
dither. Returns the dithered PNG bytes plus metadata; file writing is the
caller's job (so this stays easy to test).
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date as date_cls

from .. import prompts
from ..devicecfg import DeviceConfig
from ..settings import Settings
from ..timeutil import now_in_tz
from . import generation_client, holidays, imaging, weather

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ArtworkResult:
    device_id: str
    date: str
    image_png: bytes
    event_text_en: str | None
    event_text_he: str | None
    weather_summary: str


async def generate_artwork(settings: Settings, config: DeviceConfig) -> ArtworkResult:
    """Run the full pipeline for one device and return the dithered PNG."""
    today = now_in_tz(config.tz).date()
    date_str = today.isoformat()

    # Weather + holidays are independent — fetch concurrently.
    wx, holiday_ctx = await asyncio.gather(
        weather.fetch_weather(config.lat, config.lon),
        holidays.fetch_holidays(
            today,
            want_jewish=config.holiday_jewish,
            want_israeli=config.holiday_israeli,
            want_global=config.holiday_global,
        ),
    )

    event = await _select_event(settings, config, today, holiday_ctx)
    image_prompt = _build_image_prompt(config, wx, today, event)

    # The image render dominates latency; run narration alongside it so the
    # app-triggered path is as quick as the image call itself.
    raw_png, (narration_en, narration_he) = await asyncio.gather(
        generation_client.generate_image(settings, image_prompt),
        _narrate(settings, config, event),
    )
    dithered = imaging.to_eink_image(raw_png, fmt="PNG")

    return ArtworkResult(
        device_id=config.id,
        date=date_str,
        image_png=dithered,
        event_text_en=narration_en,
        event_text_he=narration_he,
        weather_summary=wx.as_text(config.temp_unit),
    )


async def _select_event(
    settings: Settings, config: DeviceConfig, today: date_cls, holiday_ctx
) -> str:
    holiday_block = prompts.format_holiday_context(
        holiday_ctx.jewish, holiday_ctx.israeli, holiday_ctx.global_
    )
    interests = ", ".join(config.interests) if config.interests else "general curiosity"
    prompt = prompts.EVENT_SELECTION_PROMPT.format(
        date=today.strftime("%B %d"),
        holiday_context=holiday_block,
        interests=interests,
    )
    return await generation_client.generate_text(settings, prompt)


def _build_image_prompt(config: DeviceConfig, wx, today: date_cls, event: str) -> str:
    template = config.custom_prompt_override or prompts.ARTWORK_PROMPT
    return template.format(
        condition=wx.condition,
        temperature=wx.temperature(config.temp_unit),
        date=today.strftime("%a, %b %d"),
        event=event,
        signature=config.signature,
    )


async def _narrate(
    settings: Settings, config: DeviceConfig, event: str
) -> tuple[str | None, str | None]:
    """Best-effort narration text; failures degrade to None."""
    try:
        tasks = [generation_client.generate_text(
            settings, prompts.NARRATION_EN_PROMPT.format(event=event))]
        if config.language == "he":
            tasks.append(generation_client.generate_text(
                settings, prompts.NARRATION_HE_PROMPT.format(event=event)))
        results = await asyncio.gather(*tasks)
        return results[0], (results[1] if len(results) > 1 else None)
    except Exception:  # noqa: BLE001
        logger.warning("narration generation failed", exc_info=True)
        return None, None
