"""Lightweight account auth.

An account is created on first app use and identified by a bearer token (stored
on the user's device). We persist only the SHA-256 of the token, so a DB leak
can't impersonate accounts. Email/password or magic-link can be layered on later
without changing the device or generation code.
"""
from __future__ import annotations

import hashlib
import secrets

from fastapi import Depends, Header, HTTPException

from . import repositories
from .models import Account


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_account_token() -> str:
    return secrets.token_urlsafe(32)


def create_account() -> tuple[Account, str]:
    """Create an account and return (account, plaintext_token)."""
    token = new_account_token()
    account = repositories.create_account(token_hash=hash_token(token))
    return account, token


async def require_account(
    authorization: str | None = Header(default=None),
) -> Account:
    """FastAPI dependency: resolve the bearer token to an account."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    account = repositories.get_account_by_token_hash(hash_token(token))
    if account is None:
        raise HTTPException(status_code=401, detail="invalid token")
    return account


AccountDep = Depends(require_account)
