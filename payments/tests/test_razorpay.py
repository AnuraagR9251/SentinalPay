import hashlib
import hmac
import json

from payments.protocol import redirect_is_not_success
from payments.razorpay import RazorpayConfigError, RazorpayTestAdapter


def _signed(secret: str, payload: dict) -> tuple[bytes, str]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return body, sig


def _payment_event(event_id: str, payment_id: str, status: str, created_at: int) -> dict:
    return {
        "id": event_id,
        "event": f"payment.{status}",
        "created_at": created_at,
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "amount": 24000,
                    "currency": "INR",
                    "status": status,
                    "order_id": "order_1",
                    "created_at": created_at,
                }
            }
        },
    }


def test_redirect_is_never_success() -> None:
    out = redirect_is_not_success({"razorpay_payment_id": "pay_x"})
    assert out["authoritative"] is False
    assert out["status"] == "pending"


def test_invalid_signature_rejected() -> None:
    adapter = RazorpayTestAdapter(webhook_secret="whsec")
    body, _sig = _signed("whsec", _payment_event("evt_1", "pay_1", "captured", 100))
    out = adapter.ingest_event(body=body, signature="deadbeef", headers={})
    assert out["accepted"] is False
    assert out["error"] == "invalid_signature"


def test_duplicate_and_out_of_order() -> None:
    adapter = RazorpayTestAdapter(webhook_secret="whsec")
    captured = _payment_event("evt_new", "pay_1", "captured", 200)
    authorized = _payment_event("evt_old", "pay_1", "authorized", 100)
    body_new, sig_new = _signed("whsec", captured)
    first = adapter.ingest_event(body=body_new, signature=sig_new, headers={})
    assert first["accepted"] is True
    assert first["duplicate"] is False
    again = adapter.ingest_event(body=body_new, signature=sig_new, headers={})
    assert again["duplicate"] is True
    body_old, sig_old = _signed("whsec", authorized)
    older = adapter.ingest_event(body=body_old, signature=sig_old, headers={})
    assert older.get("out_of_order") is True
    assert adapter.fetch_status("pay_1").status == "captured"


def test_create_without_keys_does_not_call_network() -> None:
    adapter = RazorpayTestAdapter(key_id="", key_secret="")
    try:
        adapter.create_or_reference(amount=10, currency="INR", receipt="r1")
    except RazorpayConfigError:
        return
    raise AssertionError("expected RazorpayConfigError")
