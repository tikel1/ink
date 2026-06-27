"""Tests for weather temperature unit handling."""
from artframe.pipeline.weather import WeatherSummary


def test_celsius_passthrough():
    w = WeatherSummary(condition="clear", temperature_c=20)
    assert w.temperature("c") == 20
    assert w.as_text("c") == "clear, 20°C"


def test_fahrenheit_conversion():
    w = WeatherSummary(condition="rain", temperature_c=0)
    assert w.temperature("f") == 32
    assert w.as_text("f") == "rain, 32°F"
