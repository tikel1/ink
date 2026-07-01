"""Fetch real billed cost from OpenAI's org Costs API, grouped by line item.

Uses the platform key. This endpoint (/v1/organization/costs) needs a key with
org read access — an unrestricted/admin key works, a scoped project key returns
401/403 (we surface that as a note and fall back to the estimate). Costs are
ORG-WIDE (all projects on the org), cached in-memory for an hour.
"""
from __future__ import annotations

import logging
import time

import httpx

from .config import get_settings

logger = logging.getLogger(__name__)

_COSTS_URL = "https://api.openai.com/v1/organization/costs"
_TTL_SECONDS = 3600
_cache: dict = {"ts": 0.0, "data": None}


async def fetch(days: int = 30) -> dict:
    now = time.time()
    if _cache["data"] is not None and now - _cache["ts"] < _TTL_SECONDS:
        return _cache["data"]

    settings = get_settings()
    key = settings.openai_admin_key or settings.platform_openai_api_key
    result = {"available": False, "total_usd": 0.0, "by_line_item": [], "days": days, "note": ""}
    if not key:
        result["note"] = "No OpenAI key configured."
        _cache.update(ts=now, data=result)
        return result

    start = int(now - days * 86400)
    agg: dict[str, float] = {}
    total = 0.0
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            page = None
            for _ in range(20):  # safety-bounded pagination
                params = {"start_time": start, "bucket_width": "1d", "limit": 180,
                          "group_by": ["line_item"]}
                if page:
                    params["page"] = page
                r = await client.get(_COSTS_URL, params=params,
                                     headers={"Authorization": f"Bearer {key}"})
                if r.status_code != 200:
                    result["note"] = (f"OpenAI Costs API returned {r.status_code} — set OPENAI_ADMIN_KEY "
                                      "to an Admin key (Dashboard → Organization → Admin keys).")
                    _cache.update(ts=now, data=result)
                    return result
                body = r.json()
                for bucket in body.get("data", []):
                    for item in bucket.get("results", []):
                        amount = ((item.get("amount") or {}).get("value")) or 0.0
                        total += amount
                        name = item.get("line_item") or "other"
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
    _cache.update(ts=now, data=result)
    return result
