"""Optional API-key gate + bearer sessions. Empty env = local demo."""

from __future__ import annotations

import hmac
import os
import time

from fastapi import HTTPException, Request

_LOGIN_WINDOW_S = 300.0
_LOGIN_MAX_FAILURES = 8


def authenticate_request(request: Request) -> str:
    expected = os.getenv("SENTINALPAY_API_KEY", "").strip()
    presented = (request.headers.get("X-API-Key") or "").strip()
    if not expected:
        return presented or request.client.host if request.client else "local"
    if not presented or not hmac.compare_digest(presented, expected):
        raise HTTPException(status_code=401, detail="invalid api key")
    return "key"


def require_login() -> bool:
    return os.getenv("SENTINALPAY_REQUIRE_LOGIN", "").strip() in {"1", "true", "yes"}


def bearer_token(request: Request) -> str | None:
    header = (request.headers.get("Authorization") or "").strip()
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
        return token or None
    return None


def require_session(request: Request) -> str:
    from risk.store import get_store

    token = bearer_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="login required")
    user_id = get_store().session_user(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid session")
    return user_id


def login_throttle_key(user_id: str, request: Request) -> str:
    host = request.client.host if request.client else "local"
    return f"{user_id.strip().lower()}|{host}"


def assert_login_not_locked(store: object, key: str) -> None:
    count = store.cache.count(f"loginfail:{key}", time.time(), _LOGIN_WINDOW_S)  # type: ignore[attr-defined]
    if count >= _LOGIN_MAX_FAILURES:
        raise HTTPException(status_code=429, detail="too many login attempts")


def note_login_failure(store: object, key: str) -> None:
    store.cache.add(f"loginfail:{key}", time.time(), _LOGIN_WINDOW_S)  # type: ignore[attr-defined]


def require_order_auth(request: Request) -> None:
    """Creating provider orders is never anonymous."""
    expected = os.getenv("SENTINALPAY_API_KEY", "").strip()
    if expected:
        authenticate_request(request)
        return
    if require_login():
        require_session(request)
        return
    raise HTTPException(status_code=401, detail="order creation requires login or SENTINALPAY_API_KEY")
