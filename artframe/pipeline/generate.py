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
        generation_client.generate_image(settings, image_prompt, config.orientation),
        _narrate(settings, config, event),
    )
    dithered = imaging.to_eink_image(raw_png, fmt="PNG", orientation=config.orientation)

    return ArtworkResult(
        device_id=config.id,
        date=date_str,
        image_png=dithered,
        event_text_en=narration_en,
        event_text_he=narration_he,
        weather_summary=wx.as_text(config.temp_unit),
    )


_EVENT_ATTEMPTS = 2


async def _select_event(
    settings: Settings, config: DeviceConfig, today: date_cls, holiday_ctx
) -> str:
    """Pick a fact-checked event for today.

    Strategy: first FORCE the topic — ask explicitly for an event in each of the
    user's interest categories (left to itself the model defaults to its favourite
    topics like space/tech and ignores the interests). If none pass the date/fact
    check, fall back to the general interest-aware selector, then a generic
    well-known event; if even that fails, return "" so the artwork is drawn with
    no event rather than a fabricated one.
    """
    date_label = today.strftime("%B %d")
    interests = [i.strip() for i in config.interests if i and i.strip()]

    # 1) Topic-forced: one explicit ask per interest, rotated by day for variety.
    if interests:
        start = today.toordinal() % len(interests)
        ordered = interests[start:] + interests[:start]
        for interest in ordered:
            event = await generation_client.generate_text(
                settings, prompts.INTEREST_EVENT_PROMPT.format(date=date_label, interest=interest))
            if event.strip().upper().startswith("NONE") or not event.strip():
                logger.info("no %s event recalled for %s", interest, date_label)
                continue
            # Light check only (is it real?) — the topic is already guaranteed by
            # the forced ask, and an on-interest event beats bouncing to an
            # off-interest fallback over an uncertain exact date.
            if await _is_real_event(settings, event):
                return event
            logger.info("%s event looked fabricated: %s", interest, event)

    # 2) General interest-aware selector.
    holiday_block = prompts.format_holiday_context(
        holiday_ctx.jewish, holiday_ctx.israeli, holiday_ctx.global_
    )
    interest_str = ", ".join(interests) if interests else "general curiosity"
    prompt = prompts.EVENT_SELECTION_PROMPT.format(
        date=date_label, holiday_context=holiday_block, interests=interest_str,
    )
    for attempt in range(_EVENT_ATTEMPTS):
        event = await generation_client.generate_text(settings, prompt)
        if await _fact_check(settings, event, date_label):
            return event
        logger.info("event failed fact-check (try %d/%d): %s",
                    attempt + 1, _EVENT_ATTEMPTS, event)

    # 3) Generic, well-known fallback — also fact-checked.
    generic = await generation_client.generate_text(
        settings, prompts.GENERIC_EVENT_PROMPT.format(date=date_label))
    if await _fact_check(settings, generic, date_label):
        return generic
    logger.warning("%s: all events failed fact-check — drawing without an event", config.id)
    return ""


async def _is_real_event(settings: Settings, event: str) -> bool:
    """True if the event is a real (non-fabricated) event — date is NOT checked."""
    if not event or not event.strip():
        return False
    try:
        verdict = await generation_client.generate_text(
            settings, prompts.REAL_EVENT_CHECK_PROMPT.format(event=event.strip()))
    except Exception:  # noqa: BLE001
        logger.warning("real-event check failed", exc_info=True)
        return False
    return verdict.strip().upper().startswith("REAL")


async def _fact_check(settings: Settings, event: str, date_label: str) -> bool:
    """True only if the model is confident the event is real and correctly dated."""
    if not event or not event.strip():
        return False
    try:
        verdict = await generation_client.generate_text(
            settings, prompts.FACT_CHECK_PROMPT.format(event=event.strip(), date=date_label))
    except Exception:  # noqa: BLE001 — an errored check shouldn't pass a bad event
        logger.warning("fact-check call failed", exc_info=True)
        return False
    return verdict.strip().upper().startswith("ACCURATE")


def _build_image_prompt(config: DeviceConfig, wx, today: date_cls, event: str) -> str:
    template = config.custom_prompt_override or prompts.ARTWORK_PROMPT
    symbol = "°F" if config.temp_unit == "f" else "°C"
    temp_str = f"{wx.temperature(config.temp_unit)}{symbol}"
    date_str = today.strftime("%a, %b %d")
    data_block = prompts.build_data_block(
        config.show_weather, config.show_date, wx.condition, temp_str, date_str, event
    )
    resolution = ("480x800 (vertical)" if config.orientation == "portrait"
                  else "800x480 (horizontal)")
    tokens = {
        "event": event, "signature": config.signature, "data_block": data_block,
        "resolution": resolution, "condition": wx.condition,
        "temperature": temp_str, "date": date_str,
    }
    # Token replacement (not str.format) so custom prompts with literal braces
    # and partial placeholders never raise.
    for key, value in tokens.items():
        template = template.replace("{" + key + "}", str(value))
    return template


async def _narrate(
    settings: Settings, config: DeviceConfig, event: str
) -> tuple[str | None, str | None]:
    """Best-effort narration text; failures degrade to None."""
    if not event or not event.strip():
        return None, None
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
