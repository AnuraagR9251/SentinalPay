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


def _argon2_hasher():
    """Argon2id for the desk admin password. Demo payer hashes stay PBKDF2."""
    from argon2 import PasswordHasher

    time_cost = int(os.getenv("SENTINALPAY_ARGON2_TIME", "3") or 3)
    memory_kib = int(os.getenv("SENTINALPAY_ARGON2_MEMORY", "65536") or 65536)
    return PasswordHasher(
        time_cost=max(1, time_cost),
        memory_cost=max(8, memory_kib),
        parallelism=1,
    )


def hash_admin_password(password: str) -> str:
    return _argon2_hasher().hash(password)


def verify_admin_password(password: str, stored: str) -> bool:
    from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

    try:
        return bool(_argon2_hasher().verify(stored, password))
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


_DUMMY_ADMIN_HASH: str | None = None


def dummy_admin_hash() -> str:
    """One Argon2 hash so a missing admin username takes the same verify path."""
    global _DUMMY_ADMIN_HASH
    if _DUMMY_ADMIN_HASH is None:
        _DUMMY_ADMIN_HASH = hash_admin_password("sentinalpay-admin-dummy")
    return _DUMMY_ADMIN_HASH
