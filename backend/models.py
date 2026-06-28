"""Immutable domain models returned by repositories."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Optional

from artframe.devicecfg import DeviceConfig


@dataclass(frozen=True)
class Account:
    id: str
    token_hash: str
    email: Optional[str]
    enc_openai_key: Optional[str]
    use_own_key: bool
    key_required: bool
    created_at: str

    @staticmethod
    def from_row(row: sqlite3.Row) -> "Account":
        return Account(
            id=row["id"],
            token_hash=row["token_hash"],
            email=row["email"],
            enc_openai_key=row["enc_openai_key"],
            use_own_key=bool(row["use_own_key"]),
            key_required=bool(row["key_required"]),
            created_at=row["created_at"],
        )


@dataclass(frozen=True)
class Device:
    id: str
    api_key: str
    account_id: Optional[str]
    pairing_code: Optional[str]
    status: str
    name: str
    tz: str
    lat: float
    lon: float
    wake_hour: int
    language: str
    temp_unit: str
    interests: str
    signature: str
    holiday_jewish: bool
    holiday_israeli: bool
    holiday_global: bool
    orientation: str
    show_date: bool
    show_weather: bool
    city_name: str
    auto_timezone: bool
    schedule: str
    schedule_days: str
    power_source: str
    sleep_after_minutes: int
    custom_prompt_override: Optional[str]
    enabled: bool
    last_seen: Optional[str]
    battery: Optional[float]
    wifi_rssi: Optional[int]
    fw_version: Optional[str]
    created_at: str

    @staticmethod
    def from_row(row: sqlite3.Row) -> "Device":
        return Device(
            id=row["id"],
            api_key=row["api_key"],
            account_id=row["account_id"],
            pairing_code=row["pairing_code"],
            status=row["status"],
            name=row["name"],
            tz=row["tz"],
            lat=row["lat"],
            lon=row["lon"],
            wake_hour=row["wake_hour"],
            language=row["language"],
            temp_unit=row["temp_unit"],
            interests=row["interests"],
            signature=row["signature"],
            holiday_jewish=bool(row["holiday_jewish"]),
            holiday_israeli=bool(row["holiday_israeli"]),
            holiday_global=bool(row["holiday_global"]),
            orientation=row["orientation"],
            show_date=bool(row["show_date"]),
            show_weather=bool(row["show_weather"]),
            city_name=row["city_name"],
            auto_timezone=bool(row["auto_timezone"]),
            schedule=row["schedule"],
            schedule_days=row["schedule_days"],
            power_source=row["power_source"],
            sleep_after_minutes=row["sleep_after_minutes"],
            custom_prompt_override=row["custom_prompt_override"],
            enabled=bool(row["enabled"]),
            last_seen=row["last_seen"],
            battery=row["battery"],
            wifi_rssi=row["wifi_rssi"],
            fw_version=row["fw_version"],
            created_at=row["created_at"],
        )

    def to_pipeline_config(self) -> DeviceConfig:
        """Adapt the DB row into the pipeline's input DTO."""
        interests = tuple(s.strip() for s in self.interests.split(",") if s.strip())
        return DeviceConfig(
            id=self.id,
            lat=self.lat,
            lon=self.lon,
            tz=self.tz,
            wake_hour=self.wake_hour,
            language=self.language,
            temp_unit=self.temp_unit,
            interests=interests,
            signature=self.signature,
            holiday_jewish=self.holiday_jewish,
            holiday_israeli=self.holiday_israeli,
            holiday_global=self.holiday_global,
            orientation=self.orientation,
            show_date=self.show_date,
            show_weather=self.show_weather,
            custom_prompt_override=self.custom_prompt_override,
            enabled=self.enabled,
        )
