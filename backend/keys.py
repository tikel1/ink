"""Effective API-key resolution — the abstraction you asked for.

Today everything runs on your platform key. When an account sets its own key,
that key is used instead. Flipping `key_required` (per account) forces the
account to supply its own key; until they do, generation is blocked and the app
shows a prompt. None of this touches the device or the pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass

from artframe.settings import Settings

from . import crypto
from .config import Settings as BackendSettings
from .config import get_settings
from .models import Account

# key_status values surfaced to the app.
STATUS_PLATFORM = "platform"   # using your key (default)
STATUS_OWN = "own"             # using the account's own key
STATUS_REQUIRED = "required"   # must set own key before generating


class KeyUnavailableError(RuntimeError):
    """No usable key for this account (own key required but not set)."""


@dataclass(frozen=True)
class KeyState:
    status: str
    has_own_key: bool


def key_state(account: Account) -> KeyState:
    if account.use_own_key and account.enc_openai_key:
        return KeyState(STATUS_OWN, True)
    if account.key_required:
        return KeyState(STATUS_REQUIRED, bool(account.enc_openai_key))
    return KeyState(STATUS_PLATFORM, bool(account.enc_openai_key))


def resolve_settings(account: Account) -> Settings:
    """Build pipeline Settings with the effective key for this account."""
    backend = get_settings()
    api_key = _effective_key(account, backend)
    return Settings(
        image_provider=backend.image_provider,
        openai_api_key=api_key,
        openai_image_model=backend.openai_image_model,
        openai_image_quality=backend.openai_image_quality,
        openai_text_model=backend.openai_text_model,
    )


def _effective_key(account: Account, backend: BackendSettings) -> str:
    if account.use_own_key and account.enc_openai_key:
        return crypto.decrypt(account.enc_openai_key)
    if account.key_required:
        raise KeyUnavailableError(
            f"account {account.id} must provide its own API key"
        )
    if not backend.platform_openai_api_key:
        raise KeyUnavailableError("platform key is not configured")
    return backend.platform_openai_api_key
