"""Optional API-key gate + bearer sessions. Empty env = local demo."""

from __future__ import annotations

import hmac
import os
import time
from typing import Any

from fastapi import HTTPException, Request

_LOGIN_WINDOW_S = 300.0
_LOGIN_MAX_FAILURES = 8
_PIN_WINDOW_S = 300.0
_PIN_MAX_FAILURES = 8
_HTTP_WINDOW_S = 60.0


def authenticate_request(request: Request) -> str:
    expected = os.getenv("SENTINALPAY_API_KEY", "").strip()
    presented = (request.headers.get("X-API-Key") or "").strip()
    if not expected:
        return presented or (request.client.host if request.client else "local")
    if not presented:
        raise HTTPException(status_code=401, detail="invalid api key")
    try:
        matched = hmac.compare_digest(presented, expected)
    except (TypeError, ValueError):
        matched = False
    if not matched:
        raise HTTPException(status_code=401, detail="invalid api key")
    return "key"


def http_rate_limit_per_min() -> int:
    raw = os.getenv("SENTINALPAY_HTTP_RATE_LIMIT_PER_MIN", "").strip()
    if raw:
        return max(1, int(raw))
    return max(1, int(os.getenv("SENTINALPAY_RATE_LIMIT_PER_MIN", "40") or 40))


def assert_http_rate_limit(client_key: str) -> None:
    """HTTP abuse limiter. Separate from payment-velocity fraud signals.

    Uses VelocityCache: Redis when SENTINALPAY_REDIS_URL connects, otherwise
    in-process (per worker, not shared, resets on restart). Demo ceiling.
    """
    from risk.store import get_store

    count = get_store().cache.add(f"http:{client_key}", time.time(), _HTTP_WINDOW_S)
    if count > http_rate_limit_per_min():
        raise HTTPException(status_code=429, detail="too many requests")


def protect_sensitive(request: Request) -> str:
    """API key when configured, then HTTP 429. Used by score/evaluate/feed/PIN."""
    client_key = authenticate_request(request)
    assert_http_rate_limit(client_key)
    return client_key


def require_login() -> bool:
    return os.getenv("SENTINALPAY_REQUIRE_LOGIN", "").strip() in {"1", "true", "yes"}


def open_access_warning() -> str | None:
    """Local demo may leave scoring open. An API key is not production user auth."""
    if require_login():
        return None
    key = os.getenv("SENTINALPAY_API_KEY", "").strip()
    if key:
        return (
            "SENTINALPAY_REQUIRE_LOGIN=0: scoring is not bound to a user session. "
            "SENTINALPAY_API_KEY gates the process, it is not end-user authentication."
        )
    return (
        "SENTINALPAY_REQUIRE_LOGIN=0 and SENTINALPAY_API_KEY is empty: "
        "score/evaluate are open local sandbox only. Not production authentication."
    )


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


def logout_request(request: Request) -> dict[str, Any]:
    """Revoke the presented bearer session. Missing/invalid token stays 401."""
    from risk.store import get_store

    token = bearer_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="login required")
    require_session(request)
    get_store().revoke_session(token)
    return {"ok": True}


def login_throttle_key(user_id: str, request: Request) -> str:
    host = request.client.host if request.client else "local"
    return f"{user_id.strip().lower()}|{host}"


def assert_login_not_locked(store: object, key: str) -> None:
    count = store.cache.count(f"loginfail:{key}", time.time(), _LOGIN_WINDOW_S)  # type: ignore[attr-defined]
    if count >= _LOGIN_MAX_FAILURES:
        raise HTTPException(status_code=429, detail="too many login attempts")


def note_login_failure(store: object, key: str) -> None:
    store.cache.add(f"loginfail:{key}", time.time(), _LOGIN_WINDOW_S)  # type: ignore[attr-defined]


def pin_throttle_key(user_id: str, request: Request) -> str:
    return login_throttle_key(user_id or "unknown", request)


def assert_pin_not_locked(store: object, key: str) -> None:
    count = store.cache.count(f"pinfail:{key}", time.time(), _PIN_WINDOW_S)  # type: ignore[attr-defined]
    if count >= _PIN_MAX_FAILURES:
        raise HTTPException(status_code=429, detail="too many pin attempts")


def note_pin_failure(store: object, key: str) -> None:
    store.cache.add(f"pinfail:{key}", time.time(), _PIN_WINDOW_S)  # type: ignore[attr-defined]


def verify_pin_request(request: Request, pin: str, challenge_id: str | None) -> dict[str, Any]:
    """Shared REST/GraphQL PIN path. Challenge caps + HTTP PIN throttle."""
    from risk.store import get_store

    protect_sensitive(request)
    store = get_store()
    token = bearer_token(request)
    cid = (challenge_id or "").strip() or None
    throttle = pin_throttle_key(cid or "standalone", request)
    assert_pin_not_locked(store, throttle)

    if cid:
        if require_login():
            user_id = require_session(request)
            token = bearer_token(request)
        else:
            challenge = store.get_challenge(cid)
            if challenge is None:
                note_pin_failure(store, throttle)
                raise HTTPException(status_code=401, detail="unknown_challenge")
            session_user = store.session_user(token) if token else None
            owner = str(challenge["user_id"])
            if session_user and session_user != owner:
                note_pin_failure(store, throttle)
                raise HTTPException(status_code=403, detail="user mismatch")
            user_id = session_user or owner
        throttle = pin_throttle_key(user_id, request)
        assert_pin_not_locked(store, throttle)
        outcome = store.verify_challenge(cid, user_id=user_id, session_token=token, pin=pin)
        if not outcome.get("ok"):
            note_pin_failure(store, throttle)
            raise HTTPException(status_code=401, detail=str(outcome.get("error") or "invalid challenge"))
        return outcome

    user_id = require_session(request)
    throttle = pin_throttle_key(user_id, request)
    assert_pin_not_locked(store, throttle)
    if not store.verify_pin(user_id, pin):
        note_pin_failure(store, throttle)
        raise HTTPException(status_code=401, detail="invalid pin")
    return {"ok": True, "sandbox": True, "note": "Sandbox PIN, not bank OTP"}


def require_order_auth(request: Request) -> None:
    """Creating provider orders is never anonymous.

    `SENTINALPAY_REQUIRE_LOGIN=1` always requires a valid bearer session, same
    as score/evaluate. `SENTINALPAY_API_KEY`, when set, is an additional
    process gate.

    Service-to-service exception: `REQUIRE_LOGIN=0` and a valid API key may
    create an order with no user session. That key is not end-user auth.
    With login off and no API key, a valid session is still required.
    """
    expected = os.getenv("SENTINALPAY_API_KEY", "").strip()
    if expected:
        authenticate_request(request)
        if require_login():
            require_session(request)
        return
    require_session(request)
