"""End-to-end pipeline test with the network + model calls stubbed out."""
import io

from PIL import Image

from artframe.devicecfg import DeviceConfig
from artframe.pipeline import generate as gen
from artframe.pipeline.holidays import HolidayContext
from artframe.pipeline.weather import WeatherSummary
from artframe.settings import Settings


def _fake_png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (1536, 1024), (200, 200, 200)).save(buf, format="PNG")
    return buf.getvalue()


async def test_generate_artwork_produces_panel_png(monkeypatch):
    captured = {}

    async def fake_weather(lat, lon):
        return WeatherSummary(condition="clear", temperature_c=25)

    async def fake_holidays(today, **kwargs):
        return HolidayContext(jewish=[], israeli=[], global_=[])

    captured["text_prompts"] = []

    async def fake_text(settings, prompt):
        captured["text_prompts"].append(prompt)
        return "Apollo 11 lands on the Moon"

    async def fake_image(settings, prompt, orientation="landscape"):
        captured["image_prompt"] = prompt
        captured["orientation"] = orientation
        return _fake_png()

    monkeypatch.setattr(gen.weather, "fetch_weather", fake_weather)
    monkeypatch.setattr(gen.holidays, "fetch_holidays", fake_holidays)
    monkeypatch.setattr(gen.generation_client, "generate_text", fake_text)
    monkeypatch.setattr(gen.generation_client, "generate_image", fake_image)

    config = DeviceConfig.from_dict(
        {"id": "t", "lat": 32.0, "lon": 34.0, "temp_unit": "f",
         "interests": ["space"], "signature": "House Kaplan"}
    )
    settings = Settings(
        image_provider="openai", openai_api_key="x",
        openai_image_model="gpt-image-1", openai_image_quality="low",
        openai_text_model="gpt-4o-mini",
    )

    result = await gen.generate_artwork(settings, config)

    with Image.open(io.BytesIO(result.image_png)) as img:
        assert img.mode == "1" and img.size == (800, 480)
    # Fahrenheit conversion flowed into the prompt + summary (25C -> 77F).
    assert "77" in captured["image_prompt"]
    assert result.weather_summary == "clear, 77°F"
    # Interests biased the event-selection prompt (the first text call).
    assert "space" in captured["text_prompts"][0]
    assert result.event_text_en == "Apollo 11 lands on the Moon"
