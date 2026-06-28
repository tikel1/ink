"""Thin wrapper around the image/text generation provider.

The API key is read from settings (environment) and never leaves the server.
Currently implements OpenAI; `gemini` raises NotImplementedError until wired.
"""
from __future__ import annotations

import base64

from openai import AsyncOpenAI

from ..constants import DISPLAY_HEIGHT, DISPLAY_WIDTH
from ..settings import Settings

# gpt-image only accepts a fixed set of sizes; pick the closest one per
# orientation and let the imaging step crop to the exact panel geometry.
_OPENAI_IMAGE_SIZE = {"landscape": "1536x1024", "portrait": "1024x1536"}


class GenerationError(RuntimeError):
    """Raised when the provider cannot produce content."""


def _require_openai(settings: Settings) -> AsyncOpenAI:
    if not settings.openai_api_key:
        raise GenerationError("OPENAI_API_KEY is not configured")
    return AsyncOpenAI(api_key=settings.openai_api_key)


async def generate_text(settings: Settings, prompt: str) -> str:
    """Return a short text completion for the given prompt."""
    if settings.image_provider != "openai":
        raise NotImplementedError(f"text provider {settings.image_provider}")

    client = _require_openai(settings)
    response = await client.chat.completions.create(
        model=settings.openai_text_model,
        messages=[{"role": "user", "content": prompt}],
    )
    text = (response.choices[0].message.content or "").strip()
    if not text:
        raise GenerationError("empty text completion")
    return text


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
        n=1,
    )
    payload = response.data[0]
    if getattr(payload, "b64_json", None):
        return base64.b64decode(payload.b64_json)
    raise GenerationError("provider returned no inline image data")


def panel_dimensions() -> tuple[int, int]:
    return (DISPLAY_WIDTH, DISPLAY_HEIGHT)
