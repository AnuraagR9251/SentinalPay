import hashlib
import hmac
import json
import time

from fastapi.testclient import TestClient

from api.main import app
from payments.razorpay import get_razorpay_adapter


def test_webhook_without_secret_is_503(monkeypatch) -> None:
    monkeypatch.setattr(get_razorpay_adapter(), "webhook_secret", "")
    client = TestClient(app)
    posted = client.post("/webhooks/razorpay", content=b"{}", headers={"X-Razorpay-Signature": "x"})
    assert posted.status_code == 503


def test_webhook_bad_sig_is_401(monkeypatch) -> None:
    adapter = get_razorpay_adapter()
    monkeypatch.setattr(adapter, "webhook_secret", "whsec")
    client = TestClient(app)
    posted = client.post("/webhooks/razorpay", content=b"{}", headers={"X-Razorpay-Signature": "nope"})
    assert posted.status_code == 401


def test_webhook_valid_sig_accepted(monkeypatch) -> None:
    adapter = get_razorpay_adapter()
    monkeypatch.setattr(adapter, "webhook_secret", "whsec")
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
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(b"whsec", body, hashlib.sha256).hexdigest()
    client = TestClient(app)
    posted = client.post("/webhooks/razorpay", content=body, headers={"X-Razorpay-Signature": sig})
    assert posted.status_code == 200
    assert posted.json()["accepted"] is True
