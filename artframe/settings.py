"""Per-generation settings passed into the pipeline.

This carries the *effective* API key + model ids for a single generation. The
backend builds one of these per device, resolving whose key to use (platform vs
the account's own). Secrets never live here at rest — only for the call.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    image_provider: str
    openai_api_key: str
    openai_image_model: str
    openai_image_quality: str
    openai_text_model: str
    # Optional Gemini (free-tier) for text + grounded search; falls back to OpenAI
    # on any error/quota. Empty key = use OpenAI for text too.
    gemini_api_key: str = ""
    gemini_text_model: str = "gemini-2.5-flash"
    # Image call route: "responses" = HA-style (a chat model rewrites the brief
    # into concrete art direction, guarded so it can't drop hard constraints,
    # with automatic fallback to direct) | "direct" = raw prompt to images API.
    openai_image_flow: str = "responses"
