"""PBKDF2 hashes. Demo seeds are not production secrets."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets

_ROUNDS = int(os.getenv("SENTINALPAY_PBKDF2_ROUNDS", "120000"))


def hash_secret(secret: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt.encode("utf-8"), _ROUNDS)
    return f"{salt}${digest.hex()}"


def hash_token(token: str) -> str:
    """SHA-256 hex of a bearer/session token. Lookup key only — not a password hash."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_secret(secret: str, stored: str) -> bool:
    if not stored or "$" not in stored:
        return False
    salt, _digest = stored.split("$", 1)
    return hmac.compare_digest(hash_secret(secret, salt), stored)
