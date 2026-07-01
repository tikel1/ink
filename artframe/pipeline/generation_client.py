"""Thin wrapper around the image/text generation provider.

The API key is read from settings (environment) and never leaves the server.
Text + grounded search prefer Gemini (free tier) when a key is set, and fall
back to OpenAI on any error/quota. Images always use OpenAI.
"""
from __future__ import annotations

import base64
import logging

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


async def generate_image(
    settings: Settings, prompt: str, orientation: str = "landscape"
) -> bytes:
    """Return raw PNG bytes for the given prompt, sized per orientation."""
    if settings.image_provider != "openai":
        raise NotImplementedError(f"image provider {settings.image_provider}")

    client = _require_openai(settings)
    response = await client.images.generate(
        model=settings.openai_image_model,
        prompt=prompt,
        size=_OPENAI_IMAGE_SIZE.get(orientation, _OPENAI_IMAGE_SIZE["landscape"]),
        quality=settings.openai_image_quality,
        n=1,
    )
    metrics.record(metrics.IMAGE, "openai")
    payload = response.data[0]
    if getattr(payload, "b64_json", None):
        return base64.b64decode(payload.b64_json)
    raise GenerationError("provider returned no inline image data")


def panel_dimensions() -> tuple[int, int]:
    return (DISPLAY_WIDTH, DISPLAY_HEIGHT)
