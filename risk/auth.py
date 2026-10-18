"""Optional API-key gate + bearer sessions. Empty env = local demo."""

from __future__ import annotations

import hmac
import os

from fastapi import HTTPException, Request


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
