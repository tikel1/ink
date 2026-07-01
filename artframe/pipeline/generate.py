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
from . import metrics
from ..constants import format_date
from ..devicecfg import DeviceConfig
from ..settings import Settings
from ..timeutil import now_in_tz
from . import generation_client, holidays, imaging, weather

logger = logging.getLogger(__name__)


class EventPick(NamedTuple):
    """An event chosen for the day: `caption` is the human text (caption +
    narration); `visual` is the iconic image the artwork should depict (may be
    empty, in which case the caption itself is the drawing subject); `now_tie` is
    an optional note on how the event connects to something happening today — it
    does NOT affect selection, only enriches the narration when present."""
    caption: str
    visual: str = ""
    now_tie: str = ""


_EMPTY_PICK = EventPick("", "")


@dataclass(frozen=True)
class ArtworkResult:
    device_id: str
    date: str
    image_png: bytes
    event_text_en: str | None
    event_text_he: str | None
    weather_summary: str
    image_prompt: str = ""        # the full prompt sent to the image model (for debug/admin)
    event_caption: str = ""       # the chosen event
    event_visual: str = ""        # the iconic visual depicted ('' = abstract)


async def generate_artwork(settings: Settings, config: DeviceConfig, on_phase=None) -> ArtworkResult:
    """Run the full pipeline for one device and return the dithered PNG.

    `on_phase(name)` (optional) is called as each stage begins, so the app can
    show the real progress: discover → research → compose → paint → finish.
    """
    def phase(name: str) -> None:
        if on_phase:
            try:
                on_phase(name)
            except Exception:  # noqa: BLE001 — progress reporting must never break generation
                pass

    today = now_in_tz(config.tz).date()
    date_str = today.isoformat()

    # Weather + holidays are independent — fetch concurrently.
    phase("discover")
    wx, holiday_ctx = await asyncio.gather(
        weather.fetch_weather(config.lat, config.lon),
        holidays.fetch_holidays(
            today,
            want_jewish=config.holiday_jewish,
            want_israeli=config.holiday_israeli,
            want_global=config.holiday_global,
        ),
    )

    # The daily event is optional: when the device turns it off, the artwork is a
    # pure abstract composition with no historical subject or caption.
    pick = _EMPTY_PICK
    if config.use_event:
        phase("research")
        pick = await _select_event(settings, config, today, holiday_ctx)
        if pick.caption and not pick.visual:
            pick = pick._replace(visual=await _derive_visual(settings, pick.caption))
    phase("compose")
    image_prompt = _build_image_prompt(config, wx, today, pick)

    # The image render dominates latency; run narration alongside it so the
    # app-triggered path is as quick as the image call itself.
    phase("paint")
    raw_png, (narration_en, narration_he) = await asyncio.gather(
        generation_client.generate_image(settings, image_prompt, config.orientation),
        _narrate(settings, config, pick.caption, pick.now_tie),
    )
    phase("finish")
    dithered = imaging.to_eink_image(raw_png, fmt="PNG", orientation=config.orientation)

    return ArtworkResult(
        device_id=config.id,
        date=date_str,
        image_png=dithered,
        event_text_en=narration_en,
        event_text_he=narration_he,
        weather_summary=wx.as_text(config.temp_unit) if config.use_weather else "",
        image_prompt=image_prompt,
        event_caption=pick.caption,
        event_visual=pick.visual,
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


async def _derive_visual(settings: Settings, caption: str) -> str:
    """Best-effort iconic image for an event when the picker didn't supply one."""
    try:
        v = await generation_client.generate_text(
            settings, prompts.VISUAL_PROMPT.format(event=caption))
        v = v.strip().strip('"').splitlines()[0][:120] if v.strip() else ""
        # The model opts out with NONE when the event has no recognizable icon —
        # keep the visual empty so the artwork stays abstract instead of forcing a
        # weird literal shape (the caption text still names the event).
        if v.strip().upper().startswith("NONE"):
            return ""
        return v
    except Exception:  # noqa: BLE001
        return ""


# All interest categories go into ONE grounded search call (the model runs several
# internal searches and returns 2-3 events per topic), so the curator sees the full
# breadth of the day at the cost of a single search. Capped only as a safety net
# against a pathologically long interests list (keeps the prompt bounded).
_MAX_SEARCH_INTERESTS = 12


def _pick_interests(interests: list[str], today: date_cls) -> list[str]:
    """The categories to search today — all of them, unless the list is absurdly
    long, in which case rotate a _MAX_SEARCH_INTERESTS-sized window by day so every
    category still cycles through over several days."""
    if len(interests) <= _MAX_SEARCH_INTERESTS:
        return interests
    start = today.toordinal() % len(interests)
    ordered = interests[start:] + interests[:start]
    return ordered[:_MAX_SEARCH_INTERESTS]


async def _search_candidates(
    settings: Settings, date_label: str, interests: list[str]
) -> list[dict]:
    """One web search across ALL categories → date-verified candidates, each tagged
    with the category it belongs to in '_interest'. [] on failure."""
    interests_block = "\n".join(f"- {i}" for i in interests)
    try:
        raw = await generation_client.generate_text_with_search(
            settings, prompts.SEARCH_EVENT_PROMPT.format(date=date_label, interests=interests_block))
    except Exception:  # noqa: BLE001 — search is best-effort
        logger.warning("web search failed", exc_info=True)
        return []
    candidates = _extract_json(raw, array=True) or []
    return [
        {**c, "_interest": (c.get("category") or "").strip()}
        for c in candidates
        if isinstance(c, dict) and c.get("on_date") and (c.get("event") or "").strip()
    ]


async def _curate_pool(
    settings: Settings, date_label: str, pool: list[dict]
) -> EventPick | None:
    """Pick the single most meaningful event from a cross-category candidate pool.
    Returns the chosen EventPick (keeping its iconic_visual), or None if empty."""
    if not pool:
        return None

    def _pick(c: dict) -> EventPick:
        return EventPick(
            c["event"].strip(),
            (c.get("iconic_visual") or "").strip(),
            (c.get("now_tie") or "").strip(),
        )

    if len(pool) == 1:
        return _pick(pool[0])

    # Deliberately omit now_tie from the listing: selection must be objective
    # (significance only). The chosen event's tie is carried through to enrich the
    # narration, but it must never bias which event wins.
    listing = "\n".join(
        f'{i+1}. [{c.get("_interest", "")}] {c["event"].strip()}'
        f'  (visual: {(c.get("iconic_visual") or "").strip()})'
        for i, c in enumerate(pool))
    chosen = pool[0]
    try:
        reply = await generation_client.generate_text(
            settings, prompts.POOL_CURATE_EVENT_PROMPT.format(date=date_label, candidates=listing))
        m = re.search(r"\d+", reply)
        if m:
            idx = int(m.group(0))
            if 1 <= idx <= len(pool):
                chosen = pool[idx - 1]
    except Exception:  # noqa: BLE001 — curation is best-effort; keep first candidate
        logger.warning("event curation failed; using first candidate", exc_info=True)
    return _pick(chosen)


async def _select_event(
    settings: Settings, config: DeviceConfig, today: date_cls, holiday_ctx
) -> EventPick:
    """Pick a date-verified, interest-matched event for today.

    1) Web search several interest categories (grounds dates in reality + returns
       iconic visuals), pool the candidates, and curate the single most meaningful
       one. 2) If search yields nothing, force the topic via the model per
       interest. 3) Then the general selector, then a generic event. If all fail,
       return an empty pick (no event drawn) rather than a fabricated one.
    """
    date_label = today.strftime("%B %d")
    interests = [i.strip() for i in config.interests if i and i.strip()]

    # 1) Web-search a few interest categories concurrently, pool every verified
    #    candidate, then pick the single most meaningful across all of them. This
    #    gives the curator breadth (no single-category tunnel vision) plus a real
    #    significance bar, so a routine release can't win over a landmark moment.
    if interests:
        chosen = _pick_interests(interests, today)
        pool = await _search_candidates(settings, date_label, chosen)
        if pool:
            logger.info("web search pooled %d candidates across %s",
                        len(pool), ", ".join(chosen))
            pick = await _curate_pool(settings, date_label, pool)
            if pick:
                logger.info("curated event: %s", pick.caption)
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
        if attempt:
            metrics.record_retry()
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
    date_str = format_date(today, config.date_format)
    data_block = prompts.build_data_block(
        config.use_weather, config.show_date,
        wx.condition, temp_str, date_str,
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


def _connection_clauses(now_tie: str) -> tuple[str, str]:
    """Build the EN/HE narration clauses that weave a present-day tie into the
    description. Empty when the event has no current connection (most events), so
    the narration stays a plain explanation."""
    tie = (now_tie or "").strip()
    if not tie:
        return "", ""
    en = (f"This event connects to the present: {tie}. Weave that contemporary link "
          "into the sentence so it bridges past and present (e.g. \"Before becoming "
          "the all-time World Cup top scorer, Messi scored his 700th goal…\"). ")
    he = (f"האירוע מתקשר להווה: {tie}. שזור את הקשר העכשווי הזה במשפט כך שיחבר בין "
          "העבר להווה. ")
    return en, he


async def _narrate(
    settings: Settings, config: DeviceConfig, event: str, now_tie: str = ""
) -> tuple[str | None, str | None]:
    """Best-effort narration text; failures degrade to None. When the event has a
    present-day tie, it's woven into the description (it never affects selection)."""
    if not event or not event.strip():
        return None, None
    conn_en, conn_he = _connection_clauses(now_tie)
    try:
        tasks = [generation_client.generate_text(
            settings, prompts.NARRATION_EN_PROMPT.format(event=event, connection=conn_en))]
        if config.language == "he":
            tasks.append(generation_client.generate_text(
                settings, prompts.NARRATION_HE_PROMPT.format(event=event, connection=conn_he)))
        results = await asyncio.gather(*tasks)
        return results[0], (results[1] if len(results) > 1 else None)
    except Exception:  # noqa: BLE001
        logger.warning("narration generation failed", exc_info=True)
        return None, None
