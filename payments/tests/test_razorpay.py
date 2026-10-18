import hashlib
import hmac
import json
import time

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
    body, _sig = _signed("whsec", _payment_event("evt_1", "pay_1", "captured", int(time.time())))
    out = adapter.ingest_event(body=body, signature="deadbeef", headers={})
    assert out["accepted"] is False
    assert out["error"] == "invalid_signature"


def test_duplicate_and_out_of_order() -> None:
    adapter = RazorpayTestAdapter(webhook_secret="whsec")
    now = int(time.time())
    captured = _payment_event("evt_new", "pay_1", "captured", now)
    authorized = _payment_event("evt_old", "pay_1", "authorized", now - 30)
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


def test_missing_event_id_and_stale_rejected() -> None:
    adapter = RazorpayTestAdapter(webhook_secret="whsec")
    body, sig = _signed("whsec", {"event": "payment.captured", "created_at": int(time.time())})
    out = adapter.ingest_event(body=body, signature=sig, headers={})
    assert out["error"] == "missing_event_id"
    stale = _payment_event("evt_old", "pay_x", "captured", 50)
    body, sig = _signed("whsec", stale)
    out = adapter.ingest_event(body=body, signature=sig, headers={})
    assert out["error"] == "stale_or_future_event"


def test_durable_ledger_survives_new_adapter(tmp_path) -> None:
    from risk.store import RiskStore

    store = RiskStore(tmp_path / "pay.db", seed_demo=False)
    now = int(time.time())
    body, sig = _signed("whsec", _payment_event("evt_d1", "pay_d1", "captured", now))
    first = RazorpayTestAdapter(webhook_secret="whsec")
    assert first.ingest_event(body=body, signature=sig, headers={}, ledger=store)["duplicate"] is False
    second = RazorpayTestAdapter(webhook_secret="whsec")
    again = second.ingest_event(body=body, signature=sig, headers={}, ledger=store)
    assert again["duplicate"] is True
    assert second.fetch_status("pay_d1", ledger=store).status == "captured"


def test_create_without_keys_does_not_call_network() -> None:
    adapter = RazorpayTestAdapter(key_id="", key_secret="")
    try:
        adapter.create_or_reference(amount=10, currency="INR", receipt="r1")
    except RazorpayConfigError:
        return
    raise AssertionError("expected RazorpayConfigError")
