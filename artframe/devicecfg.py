"""Per-device configuration — the editable state the PWA writes and the
generator reads. One JSON file per device under ./devices.

This is "the backend": the only persistent config, version-controlled in git,
edited by the Ink app.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .constants import LANGUAGES, TEMP_UNITS


@dataclass(frozen=True)
class DeviceConfig:
    id: str
    lat: float
    lon: float
    tz: str = "Asia/Jerusalem"
    wake_hour: int = 6
    language: str = "en"
    temp_unit: str = "c"
    interests: tuple[str, ...] = ()
    signature: str = "House Kaplan"
    holiday_jewish: bool = True
    holiday_israeli: bool = True
    holiday_global: bool = True
    custom_prompt_override: str | None = None
    enabled: bool = True

    def validate(self) -> None:
        """Fail fast on bad config rather than producing a broken image."""
        if self.language not in LANGUAGES:
            raise ValueError(f"{self.id}: language must be one of {LANGUAGES}")
        if self.temp_unit not in TEMP_UNITS:
            raise ValueError(f"{self.id}: temp_unit must be one of {TEMP_UNITS}")
        if not (-90 <= self.lat <= 90 and -180 <= self.lon <= 180):
            raise ValueError(f"{self.id}: lat/lon out of range")
        if not (0 <= self.wake_hour <= 23):
            raise ValueError(f"{self.id}: wake_hour must be 0-23")

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
