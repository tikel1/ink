"""Open-Meteo daily forecast (free, keyless).

Replaces the HA `weather.get_forecasts` step. Returns a small immutable summary
the prompt template can interpolate.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
REQUEST_TIMEOUT_SECONDS = 15

# Open-Meteo WMO weather codes → coarse condition words for the prompt.
_WMO_CONDITIONS = {
    0: "clear",
    1: "mostly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "fog",
    51: "drizzle",
    53: "drizzle",
    55: "drizzle",
    61: "rain",
    63: "rain",
    65: "heavy rain",
    71: "snow",
    73: "snow",
    75: "heavy snow",
    80: "rain showers",
    81: "rain showers",
    82: "heavy showers",
    95: "thunderstorm",
    96: "thunderstorm",
    99: "thunderstorm",
}


@dataclass(frozen=True)
class WeatherSummary:
    condition: str
    temperature_c: int

    def temperature(self, unit: str) -> int:
        """Temperature in the requested unit ('c' or 'f'), rounded."""
        if unit == "f":
            return round(self.temperature_c * 9 / 5 + 32)
        return self.temperature_c

    def as_text(self, unit: str = "c") -> str:
        symbol = "°F" if unit == "f" else "°C"
        return f"{self.condition}, {self.temperature(unit)}{symbol}"


async def fetch_weather(lat: float, lon: float) -> WeatherSummary:
    """Fetch today's condition + max temperature for the given location."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "weather_code,temperature_2m_max",
        "timezone": "auto",
        "forecast_days": 1,
    }
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        response = await client.get(OPEN_METEO_URL, params=params)
        response.raise_for_status()
        daily = response.json()["daily"]

    code = int(daily["weather_code"][0])
    temp = round(float(daily["temperature_2m_max"][0]))
    return WeatherSummary(
        condition=_WMO_CONDITIONS.get(code, "clear"), temperature_c=temp
    )
