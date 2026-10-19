"""Capped ASGI body reads. Do not use request.body() before this on the same request."""

from __future__ import annotations

import os

from fastapi import HTTPException, Request


def webhook_max_bytes() -> int:
    return max(1024, int(os.getenv("SENTINALPAY_WEBHOOK_MAX_BYTES", "65536") or 65536))


def _claimed_length(request: Request) -> int | None:
    raw = (request.headers.get("content-length") or "").strip()
    if not raw.isdigit():
        return None
    return int(raw)


async def read_body_capped(request: Request, max_bytes: int) -> bytes:
    """Read the ASGI stream until EOF or max_bytes. 413 as soon as the cap is exceeded.

    Content-Length is an optional early reject only. Actual bytes are always counted.
    """
    claimed = _claimed_length(request)
    if claimed is not None and claimed > max_bytes:
        raise HTTPException(status_code=413, detail="payload too large")
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=413, detail="payload too large")
        chunks.append(chunk)
    return b"".join(chunks)
