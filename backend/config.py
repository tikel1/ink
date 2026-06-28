"""Backend configuration — all secrets come from the environment only.

PLATFORM_OPENAI_API_KEY is your key (the default that pays for generation until
an account supplies its own). MASTER_ENCRYPTION_KEY encrypts per-account keys at
rest. Neither is ever returned to the app or the device.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    public_base_url: str = "http://localhost:8000"
    # Where the QR on the frame sends people to get/open the app. Empty = use
    # this backend's own /app. For production set it to the installable app URL
    # (e.g. https://tikel1.github.io/ink).
    app_url: str = ""

    # Generation provider + YOUR platform key (the default payer).
    image_provider: str = "openai"
    platform_openai_api_key: str = ""
    openai_image_model: str = "gpt-image-1"
    # low|medium|high — "low" is ~10x cheaper than the default and plenty for a
    # 1-bit thresholded e-ink panel (gpt-image-1 defaults to high otherwise).
    openai_image_quality: str = "low"
    openai_text_model: str = "gpt-4o-mini"

    # Fernet key (base64, 32 bytes) for encrypting per-account API keys at rest.
    master_encryption_key: str = ""

    # Token guarding admin endpoints (e.g. flipping an account to own-key-required).
    admin_token: str = ""

    # Storage
    data_dir: Path = Path("./data")

    # Scheduler
    generation_lead_minutes: int = 45
    enable_scheduler: bool = True

    # New-device defaults
    default_tz: str = "Asia/Jerusalem"
    default_lat: float = 32.0853
    default_lon: float = 34.7818
    default_wake_hour: int = 6

    @property
    def db_path(self) -> Path:
        return self.data_dir / "artframe.sqlite3"

    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"

    @property
    def archive_dir(self) -> Path:
        return self.data_dir / "archive"

    def ensure_dirs(self) -> None:
        for directory in (self.data_dir, self.images_dir, self.archive_dir):
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
