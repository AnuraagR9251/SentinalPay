"""Standard Checkout order + signature verify. Does not call Razorpay."""

import hashlib
import hmac

from fastapi.testclient import TestClient

from api.main import app
from payments.razorpay import RazorpayApiError


def test_create_order_rejects_small_amount() -> None:
    client = TestClient(app)
    small = client.post("/api/create-order", json={"amount": 50, "currency": "INR"})
    assert small.status_code == 400
    assert small.json()["detail"] == "minimum amount is 100 paise"


def test_create_order_and_verify_signature(monkeypatch) -> None:
    secret = "test-secret"

    class Fake:
        def create_order_paise(self, **kwargs):
            return {"order_id": "order_1", "amount": kwargs["amount_paise"], "currency": "INR"}

        def verify_checkout_signature(self, order_id, payment_id, signature):
            expected = hmac.new(secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
            return hmac.compare_digest(expected, signature)

    monkeypatch.setattr("api.main.get_razorpay_adapter", lambda: Fake())
    client = TestClient(app)
    created = client.post("/api/create-order", json={"amount": 100, "currency": "INR"})
    assert created.status_code == 200
    assert created.json()["order_id"] == "order_1"
    assert "test-secret" not in created.text
    missing = client.post(
        "/api/verify-payment",
        json={"razorpay_order_id": "", "razorpay_payment_id": "pay_1", "razorpay_signature": "x"},
    )
    assert missing.status_code == 400
    bad = client.post(
        "/api/verify-payment",
        json={"razorpay_order_id": "order_1", "razorpay_payment_id": "pay_1", "razorpay_signature": "bad"},
    )
    assert bad.status_code == 400
    good = hmac.new(secret.encode(), b"order_1|pay_1", hashlib.sha256).hexdigest()
    ok = client.post(
        "/api/verify-payment",
        json={
            "razorpay_order_id": "order_1",
            "razorpay_payment_id": "pay_1",
            "razorpay_signature": good,
        },
    )
    assert ok.status_code == 200
    assert ok.json()["ok"] is True


def test_create_order_maps_provider_auth_failure(monkeypatch) -> None:
    class Fake:
        def create_order_paise(self, **_kwargs):
            raise RazorpayApiError(401)

    monkeypatch.setattr("api.main.get_razorpay_adapter", lambda: Fake())
    client = TestClient(app)
    posted = client.post("/api/create-order", json={"amount": 100, "currency": "INR"})
    assert posted.status_code == 401
    assert posted.json()["detail"] == "razorpay auth failed"
