"""Fetch real billed cost from OpenAI's org Costs API, grouped by line item.

Uses the platform key. This endpoint (/v1/organization/costs) needs a key with
org read access — an unrestricted/admin key works, a scoped project key returns
401/403 (we surface that as a note and fall back to the estimate). Costs are
ORG-WIDE (all projects on the org), cached in-memory for an hour.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

import httpx

from .config import get_settings

logger = logging.getLogger(__name__)

_COSTS_URL = "https://api.openai.com/v1/organization/costs"
_TTL_SECONDS = 3600
# Cache keyed by (start, end, key_id) so each date window is cached independently.
_cache: dict = {}


def _to_float(value) -> float:
    """OpenAI money fields arrive as decimal strings; coerce safely to float."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _epoch(date_str: str, *, next_day: bool = False) -> int:
    """UTC midnight epoch for a YYYY-MM-DD string; next_day makes an exclusive end."""
    y, m, d = (int(x) for x in date_str.split("-"))
    base = datetime(y, m, d, tzinfo=timezone.utc)
    if next_day:
        base += timedelta(days=1)
    return int(base.timestamp())


async def fetch(start: str | None = None, end: str | None = None,
                days: int = 30) -> dict:
    """Billed OpenAI cost over a date window (YYYY-MM-DD). Falls back to the last
    `days` when no explicit window is given. Cached per-window for an hour."""
    now = time.time()
    settings = get_settings()
    key = settings.openai_admin_key or settings.platform_openai_api_key
    key_id = settings.openai_cost_api_key_id
    scope = "key" if key_id else "org"
    ck = (start, end, key_id)
    hit = _cache.get(ck)
    if hit and now - hit["ts"] < _TTL_SECONDS:
        return hit["data"]

    result = {"available": False, "total_usd": 0.0, "by_line_item": [],
              "start": start, "end": end, "scope": scope, "note": ""}
    if not key:
        result["note"] = "No OpenAI key configured."
        _cache[ck] = {"ts": now, "data": result}
        return result

    start_time = _epoch(start) if start else int(now - days * 86400)
    end_time = _epoch(end, next_day=True) if end else None
    agg: dict[str, float] = {}
    total = 0.0
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            page = None
            for _ in range(20):  # safety-bounded pagination
                params = {"start_time": start_time, "bucket_width": "1d", "limit": 180,
                          "group_by[]": ["line_item"]}
                if end_time:
                    params["end_time"] = end_time
                if key_id:  # scope spend to just the frame-generation key
                    params["api_key_ids[]"] = [key_id]
                if page:
                    params["page"] = page
                r = await client.get(_COSTS_URL, params=params,
                                     headers={"Authorization": f"Bearer {key}"})
                if r.status_code != 200:
                    result["note"] = (f"OpenAI Costs API returned {r.status_code} — set OPENAI_ADMIN_KEY "
                                      "to an Admin key (Dashboard → Organization → Admin keys).")
                    _cache[ck] = {"ts": now, "data": result}
                    return result
                body = r.json()
                for bucket in body.get("data", []):
                    for item in bucket.get("results", []):
                        # OpenAI returns amount.value as a decimal STRING (e.g. "0E-6176").
                        amount = _to_float((item.get("amount") or {}).get("value"))
                        total += amount
                        li = item.get("line_item")
                        name = li if li else "other"
                        agg[name] = agg.get(name, 0.0) + amount
                if body.get("has_more") and body.get("next_page"):
                    page = body["next_page"]
                else:
                    break
        result["available"] = True
        result["total_usd"] = round(total, 2)
        result["by_line_item"] = sorted(
            ({"name": k, "usd": round(v, 4)} for k, v in agg.items() if v > 0),
            key=lambda x: -x["usd"],
        )
    except Exception as exc:  # noqa: BLE001 — never break the overview on a billing hiccup
        logger.warning("OpenAI costs fetch failed: %s", exc)
        result["note"] = "Couldn't reach the OpenAI Costs API."
    _cache[ck] = {"ts": now, "data": result}
    return result
