"""Generate one device's daily artwork from its config.

1:1 port of the Home Assistant automation ordering: weather → event → image →
dither. Returns the dithered PNG bytes plus metadata; file writing is the
caller's job (so this stays easy to test).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import date as date_cls
from typing import NamedTuple

from .. import prompts
from ..devicecfg import DeviceConfig
from ..settings import Settings
from ..timeutil import now_in_tz
from . import generation_client, holidays, imaging, weather

logger = logging.getLogger(__name__)


class EventPick(NamedTuple):
    """An event chosen for the day: `caption` is the human text (caption +
    narration); `visual` is the iconic image the artwork should depict (may be
    empty, in which case the caption itself is the drawing subject)."""
    caption: str
    visual: str = ""


_EMPTY_PICK = EventPick("", "")


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

    pick = await _select_event(settings, config, today, holiday_ctx)
    image_prompt = _build_image_prompt(config, wx, today, pick)

    # The image render dominates latency; run narration alongside it so the
    # app-triggered path is as quick as the image call itself.
    raw_png, (narration_en, narration_he) = await asyncio.gather(
        generation_client.generate_image(settings, image_prompt, config.orientation),
        _narrate(settings, config, pick.caption),
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


def _extract_json(raw: str, array: bool):
    """Pull the first JSON array/object out of a model reply (tolerates prose)."""
    pat = r"\[.*\]" if array else r"\{.*\}"
    m = re.search(pat, raw, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


async def _search_event(settings: Settings, date_label: str, interest: str) -> EventPick | None:
    """One web search returns 3-5 date-verified candidates; a cheap no-search
    curator then picks the most iconic. Returns an EventPick or None."""
    try:
        raw = await generation_client.generate_text_with_search(
            settings, prompts.SEARCH_EVENT_PROMPT.format(date=date_label, interest=interest))
    except Exception:  # noqa: BLE001 — search is best-effort; fall back to the model
        logger.warning("web search failed for %s", interest, exc_info=True)
        return None

    candidates = _extract_json(raw, array=True) or []
    on_date = [c for c in candidates
               if isinstance(c, dict) and c.get("on_date") and (c.get("event") or "").strip()]
    if not on_date:
        return None
    if len(on_date) == 1:
        c = on_date[0]
        return EventPick(c["event"].strip(), (c.get("iconic_visual") or "").strip())

    # Curate the most iconic one (cheap, no search).
    listing = "\n".join(
        f'{i+1}. {c["event"].strip()}  [visual: {(c.get("iconic_visual") or "").strip()}]'
        for i, c in enumerate(on_date))
    try:
        choice_raw = await generation_client.generate_text(
            settings, prompts.CURATE_EVENT_PROMPT.format(date=date_label, candidates=listing))
        choice = _extract_json(choice_raw, array=False) or {}
    except Exception:  # noqa: BLE001
        choice = {}
    if (choice.get("event") or "").strip():
        return EventPick(choice["event"].strip(), (choice.get("iconic_visual") or "").strip())
    # Curation failed → fall back to the first verified candidate.
    c = on_date[0]
    return EventPick(c["event"].strip(), (c.get("iconic_visual") or "").strip())


async def _select_event(
    settings: Settings, config: DeviceConfig, today: date_cls, holiday_ctx
) -> EventPick:
    """Pick a date-verified, interest-matched event for today.

    1) Web search the day's interest (grounds the date in reality + returns the
       iconic visual to draw). 2) If search yields nothing, force the topic via
       the model per interest. 3) Then the general selector, then a generic
       event. If all fail, return an empty pick (no event drawn) rather than a
       fabricated one.
    """
    date_label = today.strftime("%B %d")
    interests = [i.strip() for i in config.interests if i and i.strip()]

    # 1) Web-search the day's focus interest (rotated by day). One search per run.
    if interests:
        start = today.toordinal() % len(interests)
        ordered = interests[start:] + interests[:start]
        for interest in ordered:
            pick = await _search_event(settings, date_label, interest)
            if pick:
                logger.info("web-search picked %s event: %s", interest, pick.caption)
                return pick

    # 2) Model-only topic-forced fallback (no search), rotated by day.
    if interests:
        start = today.toordinal() % len(interests)
        ordered = interests[start:] + interests[:start]
        for interest in ordered:
            event = await generation_client.generate_text(
                settings, prompts.INTEREST_EVENT_PROMPT.format(date=date_label, interest=interest))
            if event.strip().upper().startswith("NONE") or not event.strip():
                continue
            if await _is_real_event(settings, event):
                return EventPick(event, "")
            logger.info("%s event looked fabricated: %s", interest, event)

    # 3) General interest-aware selector.
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
            return EventPick(event, "")
        logger.info("event failed fact-check (try %d/%d): %s",
                    attempt + 1, _EVENT_ATTEMPTS, event)

    # 4) Generic, well-known fallback — also fact-checked.
    generic = await generation_client.generate_text(
        settings, prompts.GENERIC_EVENT_PROMPT.format(date=date_label))
    if await _fact_check(settings, generic, date_label):
        return EventPick(generic, "")
    logger.warning("%s: all events failed fact-check — drawing without an event", config.id)
    return _EMPTY_PICK


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


def _build_image_prompt(config: DeviceConfig, wx, today: date_cls, pick: EventPick) -> str:
    template = config.custom_prompt_override or prompts.ARTWORK_PROMPT
    symbol = "°F" if config.temp_unit == "f" else "°C"
    temp_str = f"{wx.temperature(config.temp_unit)}{symbol}"
    date_str = today.strftime("%a, %b %d")
    data_block = prompts.build_data_block(
        config.show_weather, config.show_date, wx.condition, temp_str, date_str,
        event=pick.caption, visual=pick.visual,
    )
    resolution = ("480x800 (vertical)" if config.orientation == "portrait"
                  else "800x480 (horizontal)")
    tokens = {
        "event": pick.caption, "signature": config.signature, "data_block": data_block,
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
