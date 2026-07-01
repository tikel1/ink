"""Rough cost estimation for a generation.

These are ESTIMATES for monitoring trends, not billing. Image cost is the
dominant term (one gpt-image call per generation); text/search are small and
often free (Gemini). Tune the constants if provider pricing changes.
"""
from __future__ import annotations

# USD per image by gpt-image quality (approx, medium ~ the config comment's $0.05).
IMAGE_COST_USD = {"low": 0.02, "medium": 0.05, "high": 0.19}
# Blended USD per 1K tokens for the cheap text model (input+output rough average).
TEXT_COST_PER_1K = 0.0006
# Fallback when a text call reports no token usage (e.g. Gemini free tier): a tiny
# nominal cost so call volume is still visible without over-stating spend.
TEXT_FALLBACK_PER_CALL = 0.0008
# Rough USD per web_search tool call.
SEARCH_COST_USD = 0.01


def estimate(quality: str, image_calls: int, text_calls: int,
             search_calls: int, text_tokens: int) -> float:
    image = image_calls * IMAGE_COST_USD.get(quality, IMAGE_COST_USD["medium"])
    if text_tokens > 0:
        text = (text_tokens / 1000.0) * TEXT_COST_PER_1K
    else:
        text = text_calls * TEXT_FALLBACK_PER_CALL
    search = search_calls * SEARCH_COST_USD
    return round(image + text + search, 4)
