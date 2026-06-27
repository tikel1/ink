"""Holiday context from Hebcal (Jewish) + Nager.Date (civil), both free/keyless.

Replaces the HA holiday-calendar entities. Returns human-readable holiday names
for today that the event-selection prompt can prioritize.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import httpx

HEBCAL_URL = "https://www.hebcal.com/hebcal"
NAGER_URL = "https://date.nager.at/api/v3/PublicHolidays"
REQUEST_TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class HolidayContext:
    jewish: list[str] = field(default_factory=list)
    israeli: list[str] = field(default_factory=list)
    global_: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.jewish or self.israeli or self.global_)


async def fetch_holidays(
    today: date,
    *,
    want_jewish: bool,
    want_israeli: bool,
    want_global: bool,
    country_code: str = "IL",
) -> HolidayContext:
    """Fetch holiday names for `today` from the enabled sources.

    Network failures degrade gracefully to empty lists — a missing holiday
    feed must never block the daily artwork.
    """
    jewish = await _safe(_fetch_hebcal(today)) if want_jewish else []
    civil = (
        await _safe(_fetch_nager(today, country_code))
        if (want_israeli or want_global)
        else []
    )
    return HolidayContext(
        jewish=jewish,
        israeli=civil if want_israeli else [],
        global_=civil if want_global else [],
    )


async def _safe(coro) -> list[str]:
    try:
        return await coro
    except (httpx.HTTPError, KeyError, ValueError):
        return []


async def _fetch_hebcal(today: date) -> list[str]:
    params = {
        "v": "1",
        "cfg": "json",
        "maj": "on",
        "min": "on",
        "mod": "on",
        "year": today.year,
        "month": today.month,
        "geo": "none",
    }
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.get(HEBCAL_URL, params=params)
        response.raise_for_status()
        items = response.json().get("items", [])

    stamp = today.isoformat()
    return [item["title"] for item in items if item.get("date") == stamp]


async def _fetch_nager(today: date, country_code: str) -> list[str]:
    url = f"{NAGER_URL}/{today.year}/{country_code}"
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.get(url)
        response.raise_for_status()
        items = response.json()

    stamp = today.isoformat()
    return [item["name"] for item in items if item.get("date") == stamp]
