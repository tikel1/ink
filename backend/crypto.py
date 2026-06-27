"""Symmetric encryption for per-account API keys at rest (Fernet).

The master key is an env secret. Stored ciphertext is useless without it, so a
DB leak never exposes a user's OpenAI key.
"""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings


class EncryptionError(RuntimeError):
    pass


def _fernet() -> Fernet:
    key = get_settings().master_encryption_key
    if not key:
        raise EncryptionError("MASTER_ENCRYPTION_KEY is not configured")
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise EncryptionError("MASTER_ENCRYPTION_KEY is invalid") from exc


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise EncryptionError("could not decrypt stored key") from exc


def generate_master_key() -> str:
    """Helper for setup docs: prints a fresh Fernet key."""
    return Fernet.generate_key().decode()


if __name__ == "__main__":
    print(generate_master_key())
