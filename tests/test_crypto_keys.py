"""Tests for key encryption + effective-key resolution."""
import pytest

from backend import crypto, keys, repositories
from backend.keys import KeyUnavailableError


def test_encrypt_round_trip():
    token = crypto.encrypt("sk-secret-123")
    assert token != "sk-secret-123"
    assert crypto.decrypt(token) == "sk-secret-123"


def _account(**over):
    acc = repositories.create_account(token_hash="h" + str(over))
    if "enc" in over:
        repositories.set_account_key(acc.id, over["enc"])
    if over.get("required"):
        repositories.set_key_required(acc.id, True)
    return repositories.get_account(acc.id)


def test_platform_key_is_default():
    acc = _account()
    assert keys.key_state(acc).status == keys.STATUS_PLATFORM
    assert keys.resolve_settings(acc).openai_api_key == "platform-test-key"


def test_own_key_overrides_platform():
    acc = _account(enc=crypto.encrypt("sk-user-own"))
    assert keys.key_state(acc).status == keys.STATUS_OWN
    assert keys.resolve_settings(acc).openai_api_key == "sk-user-own"


def test_required_without_key_blocks_generation():
    acc = _account(required=True)
    assert keys.key_state(acc).status == keys.STATUS_REQUIRED
    with pytest.raises(KeyUnavailableError):
        keys.resolve_settings(acc)
