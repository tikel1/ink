"""Per-device configuration — the editable state the PWA writes and the
generator reads. One JSON file per device under ./devices.

This is "the backend": the only persistent config, version-controlled in git,
edited by the Ink app.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .constants import DEFAULT_DATE_FORMAT, LANGUAGES, MAX_DATE_FORMAT_LEN, ORIENTATIONS, TEMP_UNITS


@dataclass(frozen=True)
class DeviceConfig:
    id: str
    lat: float
    lon: float
    tz: str = "Asia/Jerusalem"
    wake_hour: int = 6
    wake_minute: int = 0
    language: str = "en"
    temp_unit: str = "c"
    interests: tuple[str, ...] = ()
    signature: str = "Ink."
    holiday_jewish: bool = True
    holiday_israeli: bool = True
    holiday_global: bool = True
    orientation: str = "landscape"
    show_date: bool = True
    date_format: str = DEFAULT_DATE_FORMAT
    show_weather: bool = True
    use_weather: bool = True    # let location + weather inform the artwork/prompt
    use_event: bool = True      # tie the artwork to a moment in history
    custom_prompt_override: str | None = None
    enabled: bool = True

    def validate(self) -> None:
        """Fail fast on bad config rather than producing a broken image."""
        if self.language not in LANGUAGES:
            raise ValueError(f"{self.id}: language must be one of {LANGUAGES}")
        if self.temp_unit not in TEMP_UNITS:
            raise ValueError(f"{self.id}: temp_unit must be one of {TEMP_UNITS}")
        if self.orientation not in ORIENTATIONS:
            raise ValueError(f"{self.id}: orientation must be one of {ORIENTATIONS}")
        if not self.date_format or len(self.date_format) > MAX_DATE_FORMAT_LEN:
            raise ValueError(f"{self.id}: date_format must be 1–{MAX_DATE_FORMAT_LEN} chars")
        if not (-90 <= self.lat <= 90 and -180 <= self.lon <= 180):
            raise ValueError(f"{self.id}: lat/lon out of range")
        if not (0 <= self.wake_hour <= 23):
            raise ValueError(f"{self.id}: wake_hour must be 0-23")
        if not (0 <= self.wake_minute <= 59):
            raise ValueError(f"{self.id}: wake_minute must be 0-59")

    @staticmethod
    def from_dict(data: dict) -> "DeviceConfig":
        known = {f for f in DeviceConfig.__dataclass_fields__}
        clean = {k: v for k, v in data.items() if k in known}
        if "interests" in clean and isinstance(clean["interests"], list):
            clean["interests"] = tuple(clean["interests"])
        config = DeviceConfig(**clean)
        config.validate()
        return config


def load_devices(devices_dir: Path) -> list[DeviceConfig]:
    """Load every <id>.json under devices_dir (skipping examples)."""
    if not devices_dir.exists():
        return []
    configs: list[DeviceConfig] = []
    for path in sorted(devices_dir.glob("*.json")):
        if path.stem.startswith("_") or path.stem == "example":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("id", path.stem)
        configs.append(DeviceConfig.from_dict(data))
    return configs
