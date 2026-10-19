import asyncio
import hashlib
import hmac
import json
import time

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from api.httpbody import read_body_capped
from api.main import app
from payments.razorpay import get_razorpay_adapter

SECRET = b"whsec"


def _sign(body: bytes) -> str:
    return hmac.new(SECRET, body, hashlib.sha256).hexdigest()


def _payment_body(**overrides) -> bytes:
    payload = {
        "id": "evt_http_1",
        "created_at": int(time.time()),
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_http_1",
                    "amount": 100,
                    "currency": "INR",
                    "status": "captured",
                    "created_at": int(time.time()),
                }
            }
        },
    }
    payload.update(overrides)
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def _pad(body: bytes, size: int) -> bytes:
    if len(body) > size:
        raise AssertionError("payload already larger than pad target")
    return body + (b" " * (size - len(body)))


class _StreamRequest:
    def __init__(self, chunks: list[bytes], headers: dict[str, str] | None = None) -> None:
        self._chunks = chunks
        self.headers = headers or {}

    async def stream(self):
        for chunk in self._chunks:
            yield chunk


def _enable_secret(monkeypatch) -> None:
    monkeypatch.setattr(get_razorpay_adapter(), "webhook_secret", SECRET.decode())


def test_webhook_without_secret_is_503(monkeypatch) -> None:
    monkeypatch.setattr(get_razorpay_adapter(), "webhook_secret", "")
    client = TestClient(app)
    posted = client.post("/webhooks/razorpay", content=b"{}", headers={"X-Razorpay-Signature": "x"})
    assert posted.status_code == 503


def test_webhook_bad_sig_is_401(monkeypatch) -> None:
    _enable_secret(monkeypatch)
    client = TestClient(app)
    posted = client.post("/webhooks/razorpay", content=b"{}", headers={"X-Razorpay-Signature": "nope"})
    assert posted.status_code == 401


def test_webhook_valid_sig_accepted(monkeypatch) -> None:
    _enable_secret(monkeypatch)
    body = _payment_body()
    client = TestClient(app)
    posted = client.post("/webhooks/razorpay", content=body, headers={"X-Razorpay-Signature": _sign(body)})
    assert posted.status_code == 200
    assert posted.json()["accepted"] is True


def test_webhook_body_below_limit_accepted(monkeypatch) -> None:
    _enable_secret(monkeypatch)
    monkeypatch.setenv("SENTINALPAY_WEBHOOK_MAX_BYTES", "1024")
    body = _pad(_payment_body(id="evt_below"), 800)
    client = TestClient(app)
    posted = client.post("/webhooks/razorpay", content=body, headers={"X-Razorpay-Signature": _sign(body)})
    assert posted.status_code == 200
    assert posted.json()["accepted"] is True


def test_webhook_body_exactly_at_limit_accepted(monkeypatch) -> None:
    _enable_secret(monkeypatch)
    monkeypatch.setenv("SENTINALPAY_WEBHOOK_MAX_BYTES", "1024")
    body = _pad(_payment_body(id="evt_exact"), 1024)
    assert len(body) == 1024
    client = TestClient(app)
    posted = client.post("/webhooks/razorpay", content=body, headers={"X-Razorpay-Signature": _sign(body)})
    assert posted.status_code == 200
    assert posted.json()["accepted"] is True


def test_webhook_body_over_limit_is_413(monkeypatch) -> None:
    _enable_secret(monkeypatch)
    monkeypatch.setenv("SENTINALPAY_WEBHOOK_MAX_BYTES", "1024")
    verified: list[object] = []
    ingested: list[object] = []
    adapter = get_razorpay_adapter()
    original_ingest = adapter.ingest_event

    def _ingest(**kwargs):
        ingested.append(kwargs)
        return original_ingest(**kwargs)

    monkeypatch.setattr(adapter, "verify_signature", lambda *args, **kwargs: verified.append(1) or True)
    monkeypatch.setattr(adapter, "ingest_event", _ingest)
    client = TestClient(app)
    posted = client.post(
        "/webhooks/razorpay",
        content=b"{" + (b"a" * 2000) + b"}",
        headers={"X-Razorpay-Signature": "x"},
    )
    assert posted.status_code == 413
    assert verified == []
    assert ingested == []


def test_webhook_oversized_without_content_length() -> None:
    async def _run() -> None:
        req = _StreamRequest([b"x" * 600, b"x" * 600], headers={})
        with pytest.raises(HTTPException) as raised:
            await read_body_capped(req, 1024)
        assert raised.value.status_code == 413

    asyncio.run(_run())


def test_webhook_inaccurate_content_length_still_caps() -> None:
    async def _run() -> None:
        req = _StreamRequest([b"x" * 800, b"x" * 800], headers={"content-length": "10"})
        with pytest.raises(HTTPException) as raised:
            await read_body_capped(req, 1024)
        assert raised.value.status_code == 413

    asyncio.run(_run())


def test_claimed_length_over_max_does_not_read_stream() -> None:
    class Boom:
        headers = {"content-length": "9999"}

        async def stream(self):
            raise AssertionError("must not read body when Content-Length already exceeds max")
            yield b""  # pragma: no cover

    async def _run() -> None:
        with pytest.raises(HTTPException) as raised:
            await read_body_capped(Boom(), 1024)
        assert raised.value.status_code == 413

    asyncio.run(_run())


def test_webhook_empty_body_is_401(monkeypatch) -> None:
    _enable_secret(monkeypatch)
    client = TestClient(app)
    posted = client.post("/webhooks/razorpay", content=b"", headers={"X-Razorpay-Signature": _sign(b"")})
    assert posted.status_code == 401


def test_capped_read_empty_body_returns_empty() -> None:
    async def _run() -> None:
        got = await read_body_capped(_StreamRequest([], headers={"content-length": "0"}), 1024)
        assert got == b""

    asyncio.run(_run())


def test_capped_read_keeps_exact_bytes_for_hmac() -> None:
    async def _run() -> None:
        raw = b'{"id":"evt-keep"}'
        req = _StreamRequest([raw[:5], raw[5:]], headers={"content-length": str(len(raw))})
        got = await read_body_capped(req, 1024)
        assert got == raw
        assert _sign(got) == _sign(raw)

    asyncio.run(_run())
