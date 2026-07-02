"""Thin wrapper around the image/text generation provider.

The API key is read from settings (environment) and never leaves the server.
Text + grounded search prefer Gemini (free tier) when a key is set, and fall
back to OpenAI on any error/quota. Images always use OpenAI.
"""
from __future__ import annotations

import base64
import logging
from typing import NamedTuple

from openai import AsyncOpenAI

from ..constants import DISPLAY_HEIGHT, DISPLAY_WIDTH
from ..settings import Settings
from . import metrics

logger = logging.getLogger(__name__)


def _tokens(resp) -> int:
    """Best-effort total-token count across OpenAI/Gemini response shapes."""
    usage = getattr(resp, "usage", None) or getattr(resp, "usage_metadata", None)
    if usage is None:
        return 0
    for attr in ("total_tokens", "total_token_count"):
        val = getattr(usage, attr, None)
        if isinstance(val, int):
            return val
    return 0

# gpt-image only accepts a fixed set of sizes; pick the closest one per
# orientation and let the imaging step crop to the exact panel geometry.
_OPENAI_IMAGE_SIZE = {"landscape": "1536x1024", "portrait": "1024x1536"}


class GenerationError(RuntimeError):
    """Raised when the provider cannot produce content."""


def _require_openai(settings: Settings) -> AsyncOpenAI:
    if not settings.openai_api_key:
        raise GenerationError("OPENAI_API_KEY is not configured")
    return AsyncOpenAI(api_key=settings.openai_api_key)


async def _gemini_text(settings: Settings, prompt: str, search: bool) -> str:
    """Gemini text (optionally with Google Search grounding). Raises on failure."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.gemini_api_key)
    config = None
    if search:
        config = types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())])
    resp = await client.aio.models.generate_content(
        model=settings.gemini_text_model, contents=prompt, config=config)
    metrics.record(metrics.SEARCH if search else metrics.TEXT, "gemini", _tokens(resp))
    return (resp.text or "").strip()


async def _openai_text(settings: Settings, prompt: str) -> str:
    client = _require_openai(settings)
    response = await client.chat.completions.create(
        model=settings.openai_text_model,
        messages=[{"role": "user", "content": prompt}],
    )
    metrics.record(metrics.TEXT, "openai", _tokens(response))
    return (response.choices[0].message.content or "").strip()


async def _openai_search(settings: Settings, prompt: str) -> str:
    client = _require_openai(settings)
    response = await client.responses.create(
        model=settings.openai_text_model,
        tools=[{"type": "web_search"}],
        input=prompt,
    )
    metrics.record(metrics.SEARCH, "openai", _tokens(response))
    return (getattr(response, "output_text", "") or "").strip()


async def generate_text(settings: Settings, prompt: str) -> str:
    """Short text completion. Gemini (free) first, OpenAI fallback on error/quota."""
    if settings.gemini_api_key:
        try:
            text = await _gemini_text(settings, prompt, search=False)
            if text:
                return text
        except Exception:  # noqa: BLE001 — any Gemini error/quota -> OpenAI
            logger.warning("gemini text failed; falling back to OpenAI", exc_info=True)
    text = await _openai_text(settings, prompt)
    if not text:
        raise GenerationError("empty text completion")
    return text


async def generate_text_with_search(settings: Settings, prompt: str) -> str:
    """Text grounded by live web search (to verify event dates). Gemini's free
    Google Search grounding first; OpenAI's web_search as fallback on error/quota."""
    if settings.gemini_api_key:
        try:
            text = await _gemini_text(settings, prompt, search=True)
            if text:
                return text
        except Exception:  # noqa: BLE001 — any Gemini error/quota -> OpenAI
            logger.warning("gemini search failed; falling back to OpenAI", exc_info=True)
    return await _openai_search(settings, prompt)


class ImageResult(NamedTuple):
    """Raw PNG bytes + the prompt the image model actually saw ('' = ours,
    verbatim — the direct flow; non-empty = the responses-flow rewrite)."""
    png: bytes
    revised_prompt: str = ""


# Instructions for the chat model that fronts the image tool in the responses
# flow. It concretizes our long brief (which the image model renders better) but
# is contractually forbidden from dropping the parts that must survive verbatim —
# the exact failure mode of Home Assistant's equivalent flow (tiny captions,
# converted temperature units).
_REWRITE_GUARD = """You are an art director preparing a prompt for an image model.
Rewrite the brief you receive into ONE concrete, visual, scene-first image prompt
(about 150-250 words) and call the image generation tool exactly once.

HARD REQUIREMENTS — your image prompt MUST:
- Contain each of these text fragments VERBATIM, exact characters, never reworded,
  never unit-converted:
{must}
- Keep: pure white background, deep matte black hand-cut paper shapes only, no
  other colors, rough torn hand-cut edges, subtle paper texture.
{extra}
Preserve the brief's artistic intent (abstract Matisse cut-paper, data dissolved
into the shapes as negative space); make the language concrete rather than meta.
Never add subjects, events, captions, or symbols the brief does not ask for."""


# Caption rules — only when the brief actually has an event. Baking these into
# the static guard forced a caption on event-less artworks, and the rewriter
# INVENTED a historical event from the date to satisfy it.
CAPTION_RULES = """- The caption along the bottom edge is in LARGE BOLD CAPITAL
  LETTERS with wide letter-spacing, cap height at least 3% of the image height —
  never small, thin, or subtle in size.
- The caption is a 3-7 word magazine-style HEADLINE naming the achievement or
  moment itself, ending with the year. Month names and day numbers are FORBIDDEN
  in the caption — the full date already appears inside the artwork. Example:
  write "INDEPENDENCE VOTED, 1776", never "JULY 2 1776 INDEPENDENCE VOTED"."""

NO_CAPTION_RULES = """- There is NO event today: the artwork must contain NO
  caption, NO headline, and NO event symbol. Do NOT invent a historical event
  from the date. The only text in the artwork is the fragments listed above; the
  composition is purely abstract shapes plus the dissolved date/weather data."""


def _revision_ok(revised: str, must_include: list[str], expect_caption: bool) -> bool:
    """True if the rewrite kept every hard constraint (else we fall back). The
    bold-caption check only applies when the artwork should HAVE a caption —
    an event-less brief legitimately has none."""
    if not revised:
        return False
    if expect_caption and "bold" not in revised.lower():
        return False
    return all(fragment in revised for fragment in must_include)


async def _openai_image_direct(
    client: AsyncOpenAI, settings: Settings, prompt: str, size: str
) -> ImageResult:
    """Today's path: our prompt goes to the image model verbatim."""
    response = await client.images.generate(
        model=settings.openai_image_model,
        prompt=prompt,
        size=size,
        quality=settings.openai_image_quality,
        n=1,
    )
    metrics.record(metrics.IMAGE, "openai")
    payload = response.data[0]
    if getattr(payload, "b64_json", None):
        return ImageResult(base64.b64decode(payload.b64_json))
    raise GenerationError("provider returned no inline image data")


async def _openai_image_responses(
    client: AsyncOpenAI, settings: Settings, prompt: str, size: str,
    must_include: list[str], extra_rules: str = "", expect_caption: bool = True,
) -> ImageResult:
    """HA-style path: a chat model rewrites the brief into concrete art direction
    (guarded), then calls the image tool. Raises on any miss — caller falls back."""
    must = "\n".join(f'  - "{s}"' for s in must_include) or "  (none)"
    extra = (extra_rules.rstrip() + "\n") if extra_rules else ""
    tool = {
        "type": "image_generation",
        "size": size,
        "quality": settings.openai_image_quality,
        "output_format": "png",
    }
    response = await client.responses.create(
        model=settings.openai_text_model,
        instructions=_REWRITE_GUARD.format(must=must, extra=extra),
        input=prompt,
        tools=[tool],
        tool_choice="required",
    )
    image_b64, revised = None, ""
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", "") == "image_generation_call":
            image_b64 = getattr(item, "result", None)
            revised = getattr(item, "revised_prompt", "") or ""
    if not image_b64:
        raise GenerationError("responses flow returned no image")
    if not _revision_ok(revised, must_include, expect_caption):
        raise GenerationError(f"rewrite dropped a hard constraint: {revised[:160]!r}")
    metrics.record(metrics.IMAGE, "openai")
    return ImageResult(base64.b64decode(image_b64), revised)


async def generate_image(
    settings: Settings, prompt: str, orientation: str = "landscape",
    must_include: list[str] | None = None, extra_rules: str = "",
    expect_caption: bool = True,
) -> ImageResult:
    """Generate the artwork PNG. Prefers the responses flow (richer images from
    concretized prompts) when enabled; any error or a rewrite that loses a hard
    constraint falls back to the direct flow, so the worst case is exactly the
    old behavior. `extra_rules` are per-generation guard lines (e.g. how to treat
    the weather icon / signature) — instructions for the rewriter, not validated.
    `expect_caption` is False for event-less artworks (no caption to validate)."""
    if settings.image_provider != "openai":
        raise NotImplementedError(f"image provider {settings.image_provider}")

    client = _require_openai(settings)
    size = _OPENAI_IMAGE_SIZE.get(orientation, _OPENAI_IMAGE_SIZE["landscape"])
    if settings.openai_image_flow == "responses":
        try:
            return await _openai_image_responses(
                client, settings, prompt, size, must_include or [], extra_rules,
                expect_caption)
        except Exception:  # noqa: BLE001 — the direct path is always the safety net
            logger.warning("responses image flow failed; falling back to direct",
                           exc_info=True)
    return await _openai_image_direct(client, settings, prompt, size)


def panel_dimensions() -> tuple[int, int]:
    return (DISPLAY_WIDTH, DISPLAY_HEIGHT)
