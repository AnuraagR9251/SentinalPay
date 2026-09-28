"""Optional API-key gate. Empty env = local demo, no secret baked in."""

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
