"""Checkout policy is enforced on the server. Razorpay HTTP is mocked."""

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from api.main import app
from payments.protocol import PaymentRef
from payments.razorpay import RazorpayApiError, get_razorpay_adapter
from risk.store import get_store

SECRET = "test-secret"


def _login(client: TestClient) -> dict[str, str]:
    token = client.post("/login", json={"user_id": "aarav@senitenial", "password": "demo123"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _body(**extra) -> dict:
    payload = {
        "amount": 100,
        "currency": "INR",
        "transaction_id": "tx-checkout-1",
        "user_id": "aarav@senitenial",
        "merchant_id": "shop@upi",
    }
    payload.update(extra)
    return payload


def _sign(order_id: str = "order_1", payment_id: str = "pay_1") -> str:
    return hmac.new(SECRET.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()


class Fake:
    def __init__(self, status: str = "captured", amount: float = 1.0, currency: str = "INR", order_id: str = "order_1"):
        self.creates = 0
        self.fetches = 0
        self.status = status
        self.amount = amount
        self.currency = currency
        self.order_id = order_id

    def create_order_paise(self, **kwargs):
        self.creates += 1
        return {"order_id": "order_1", "amount": kwargs["amount_paise"], "currency": kwargs.get("currency", "INR")}

    def verify_checkout_signature(self, order_id, payment_id, signature):
        expected = hmac.new(SECRET.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature or "")

    def fetch_status(self, payment_id, ledger=None):
        self.fetches += 1
        return PaymentRef(
            provider="razorpay_test",
            provider_payment_id=payment_id,
            amount=self.amount,
            currency=self.currency,
            status=self.status,
            order_id=self.order_id,
        )


def _patch(monkeypatch, action: str, fake: Fake | None = None, decision: str | None = None):
    fake = fake or Fake()

    def evaluate(raw, **_kwargs):
        return {
            "transaction_id": raw["transaction_id"],
            "user_id": raw["user_id"],
            "action": action,
            "decision": decision or action,
            "risk_score": 40,
            "challenge_id": "ch-step" if action == "STEP_UP" else None,
        }

    monkeypatch.setattr("api.main.evaluate_transaction", evaluate)
    monkeypatch.setattr("api.main.get_razorpay_adapter", lambda: fake)
    return fake


def test_open_sandbox_checkout_does_not_require_login(monkeypatch) -> None:
    fake = _patch(monkeypatch, "ALLOW", decision="ALLOW")
    client = TestClient(app)
    posted = client.post("/api/create-order", json=_body(transaction_id="tx-open"))
    assert posted.status_code == 200
    assert posted.json()["order_id"] == "order_1"
    assert fake.creates == 1
    client = TestClient(app)
    small = client.post("/api/create-order", json={"amount": 50, "currency": "INR"})
    assert small.status_code == 400
    assert small.json()["detail"] == "minimum amount is 100 paise"


def test_direct_order_without_evaluation_does_not_call_razorpay(monkeypatch) -> None:
    fake = _patch(monkeypatch, "ALLOW")
    called = {"n": 0}

    def evaluate(*_args, **_kwargs):
        called["n"] += 1
        raise AssertionError("evaluation must not run without a transaction")

    monkeypatch.setattr("api.main.evaluate_transaction", evaluate)
    client = TestClient(app)
    posted = client.post("/api/create-order", headers=_login(client), json={"amount": 100, "currency": "INR"})
    assert posted.status_code == 400
    assert posted.json()["detail"] == "missing fields"
    assert fake.creates == 0
    assert called["n"] == 0


def test_allow_creates_one_order_and_replays_it(monkeypatch) -> None:
    fake = _patch(monkeypatch, "ALLOW", decision="ALLOW")
    client = TestClient(app)
    headers = _login(client)
    first = client.post("/api/create-order", headers=headers, json=_body())
    second = client.post("/api/create-order", headers=headers, json=_body())
    assert first.status_code == 200
    assert first.json()["order_id"] == "order_1"
    assert first.json()["action"] == "ALLOW"
    assert first.json()["settled"] is False
    assert second.status_code == 200
    assert second.json()["order_id"] == "order_1"
    assert fake.creates == 1
    saved = get_store().get_checkout_by_transaction("tx-checkout-1")
    assert saved["order_id"] == "order_1"
    assert saved["payment_status"] == "none"


def test_block_rejects_before_razorpay(monkeypatch) -> None:
    fake = _patch(monkeypatch, "BLOCK", decision="BLOCK")
    client = TestClient(app)
    posted = client.post("/api/create-order", headers=_login(client), json=_body())
    assert posted.status_code == 403
    assert posted.json()["detail"]["action"] == "BLOCK"
    assert fake.creates == 0
    assert get_store().get_checkout_by_transaction("tx-checkout-1") is None


def test_manual_review_does_not_bypass_hold(monkeypatch) -> None:
    fake = _patch(monkeypatch, "HOLD", decision="REVIEW")
    now = datetime.now(timezone.utc).isoformat()
    store = get_store()
    with store._connect() as conn:
        conn.execute(
            """
            INSERT INTO review_cases (transaction_id, status, original_score, created_at)
            VALUES ('tx-hold', 'PENDING', 40, ?)
            """,
            (now,),
        )
        conn.commit()
    store.submit_review("tx-hold", "APPROVED", "desk")
    client = TestClient(app)
    denied = client.post("/api/create-order", headers=_login(client), json=_body(transaction_id="tx-hold"))
    assert denied.status_code == 403
    assert denied.json()["detail"]["action"] == "HOLD"
    assert denied.json()["detail"]["secondary_outcome"] == "CONTINUE_HOLD"
    assert fake.creates == 0
    assert get_store().get_checkout_by_transaction("tx-hold") is None


def test_step_up_requires_consumed_challenge(monkeypatch) -> None:
    fake = _patch(monkeypatch, "STEP_UP", decision="REVIEW")
    client = TestClient(app)
    headers = _login(client)
    denied = client.post("/api/create-order", headers=headers, json=_body(transaction_id="tx-step"))
    assert denied.status_code == 403
    assert denied.json()["detail"]["action"] == "STEP_UP"
    assert denied.json()["detail"]["challenge_id"] == "ch-step"
    assert fake.creates == 0
    now = datetime.now(timezone.utc).isoformat()
    store = get_store()
    with store._connect() as conn:
        conn.execute(
            """
            INSERT INTO challenges (
                challenge_id, user_id, session_token, transaction_id,
                created_at, expires_at, attempts, max_attempts, consumed_at
            ) VALUES ('ch-step', 'aarav@senitenial', NULL, 'tx-step', ?, ?, 1, 3, ?)
            """,
            (now, now, now),
        )
        conn.commit()
    allowed = client.post("/api/create-order", headers=headers, json=_body(transaction_id="tx-step"))
    assert allowed.status_code == 200
    assert fake.creates == 1


def test_provider_auth_failure_releases_the_claim(monkeypatch) -> None:
    def evaluate(raw, **_kwargs):
        return {"transaction_id": raw["transaction_id"], "user_id": raw["user_id"], "action": "ALLOW", "decision": "ALLOW", "risk_score": 1}

    class Boom:
        def create_order_paise(self, **_kwargs):
            raise RazorpayApiError(401)

    monkeypatch.setattr("api.main.evaluate_transaction", evaluate)
    monkeypatch.setattr("api.main.get_razorpay_adapter", lambda: Boom())
    client = TestClient(app)
    posted = client.post("/api/create-order", headers=_login(client), json=_body())
    assert posted.status_code == 401
    assert posted.json()["detail"] == "razorpay auth failed"
    assert get_store().get_checkout_by_transaction("tx-checkout-1") is None


def _paid(client: TestClient, headers: dict[str, str], monkeypatch, fake: Fake, transaction_id: str = "tx-pay"):
    _patch(monkeypatch, "ALLOW", fake, decision="ALLOW")
    created = client.post("/api/create-order", headers=headers, json=_body(transaction_id=transaction_id))
    assert created.status_code == 200
    return created.json()["order_id"]


def test_invalid_signature(monkeypatch) -> None:
    fake = Fake()
    client = TestClient(app)
    headers = _login(client)
    order_id = _paid(client, headers, monkeypatch, fake)
    posted = client.post(
        "/api/verify-payment",
        headers=headers,
        json={"razorpay_order_id": order_id, "razorpay_payment_id": "pay_1", "razorpay_signature": "bad"},
    )
    assert posted.status_code == 400
    assert posted.json()["detail"] == "signature mismatch"
    assert get_store().get_checkout_order(order_id)["payment_status"] == "none"


def test_amount_currency_and_order_mismatches(monkeypatch) -> None:
    client = TestClient(app)
    headers = _login(client)
    fake = Fake(amount=5.0)
    order_id = _paid(client, headers, monkeypatch, fake, "tx-mismatch")
    amount = client.post(
        "/api/verify-payment",
        headers=headers,
        json={"razorpay_order_id": order_id, "razorpay_payment_id": "pay_1", "razorpay_signature": _sign(order_id)},
    )
    assert amount.status_code == 400
    assert amount.json()["detail"] == "amount mismatch"
    fake.amount = 1.0
    fake.currency = "USD"
    currency = client.post(
        "/api/verify-payment",
        headers=headers,
        json={"razorpay_order_id": order_id, "razorpay_payment_id": "pay_1", "razorpay_signature": _sign(order_id)},
    )
    assert currency.status_code == 400
    assert currency.json()["detail"] == "currency mismatch"
    fake.currency = "INR"
    fake.order_id = "order_other"
    mismatched = client.post(
        "/api/verify-payment",
        headers=headers,
        json={"razorpay_order_id": order_id, "razorpay_payment_id": "pay_1", "razorpay_signature": _sign(order_id)},
    )
    assert mismatched.status_code == 400
    assert mismatched.json()["detail"] == "order mismatch"
    wrong_txn = client.post(
        "/api/verify-payment",
        headers=headers,
        json={
            "razorpay_order_id": order_id,
            "razorpay_payment_id": "pay_1",
            "razorpay_signature": _sign(order_id),
            "transaction_id": "tx-other",
        },
    )
    assert wrong_txn.status_code == 400
    assert wrong_txn.json()["detail"] == "order mismatch"
    assert get_store().get_checkout_order(order_id)["payment_status"] == "none"


def test_failed_payment_is_persisted_and_not_settled(monkeypatch) -> None:
    client = TestClient(app)
    headers = _login(client)
    fake = Fake(status="failed")
    order_id = _paid(client, headers, monkeypatch, fake, "tx-fail")
    posted = client.post(
        "/api/verify-payment",
        headers=headers,
        json={"razorpay_order_id": order_id, "razorpay_payment_id": "pay_fail", "razorpay_signature": _sign(order_id, "pay_fail")},
    )
    assert posted.status_code == 200
    assert posted.json()["ok"] is False
    assert posted.json()["settled"] is False
    assert posted.json()["payment_status"] == "failed"
    assert get_store().get_checkout_order(order_id)["payment_status"] == "failed"


def test_captured_payment_persists_and_duplicate_callback_does_not_refetch(monkeypatch) -> None:
    client = TestClient(app)
    headers = _login(client)
    fake = Fake(status="captured")
    order_id = _paid(client, headers, monkeypatch, fake, "tx-ok")
    body = {
        "razorpay_order_id": order_id,
        "razorpay_payment_id": "pay_ok",
        "razorpay_signature": _sign(order_id, "pay_ok"),
        "transaction_id": "tx-ok",
    }
    first = client.post("/api/verify-payment", headers=headers, json=body)
    second = client.post("/api/verify-payment", headers=headers, json=body)
    assert first.status_code == 200
    assert first.json()["settled"] is True
    assert first.json()["payment_status"] == "captured"
    assert second.json() == first.json()
    assert fake.fetches == 1
    assert get_store().get_checkout_order(order_id)["payment_status"] == "captured"


def test_authorized_signature_is_not_settled(monkeypatch) -> None:
    client = TestClient(app)
    headers = _login(client)
    fake = Fake(status="authorized")
    order_id = _paid(client, headers, monkeypatch, fake, "tx-auth")
    posted = client.post(
        "/api/verify-payment",
        headers=headers,
        json={"razorpay_order_id": order_id, "razorpay_payment_id": "pay_auth", "razorpay_signature": _sign(order_id, "pay_auth")},
    )
    assert posted.status_code == 200
    assert posted.json()["ok"] is True
    assert posted.json()["settled"] is False
    assert posted.json()["payment_status"] == "authorized"


def _webhook(order_id: str, event_id: str, status: str, created_at: int) -> bytes:
    return json.dumps(
        {
            "id": event_id,
            "created_at": created_at,
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_hook",
                        "amount": 100,
                        "currency": "INR",
                        "status": status,
                        "order_id": order_id,
                        "created_at": created_at,
                    }
                }
            },
        },
        separators=(",", ":"),
    ).encode()


def test_webhook_duplicate_and_older_event_do_not_regress(monkeypatch) -> None:
    monkeypatch.setattr(get_razorpay_adapter(), "webhook_secret", "whsec")
    store = get_store()
    store.begin_checkout_order(transaction_id="tx-hook", user_id="aarav@senitenial", amount_paise=100, currency="INR")
    store.attach_checkout_order("tx-hook", "order_hook")
    client = TestClient(app)
    now = int(time.time())

    def post(event_id: str, status: str, created_at: int):
        body = _webhook("order_hook", event_id, status, created_at)
        signature = hmac.new(b"whsec", body, hashlib.sha256).hexdigest()
        return client.post("/webhooks/razorpay", content=body, headers={"X-Razorpay-Signature": signature, "X-Razorpay-Event-Id": event_id})

    captured = post("evt_new", "captured", now)
    duplicate = post("evt_new", "captured", now)
    older = post("evt_old", "authorized", now - 500)
    assert captured.status_code == 200
    assert duplicate.json()["duplicate"] is True
    assert older.json()["out_of_order"] is True
    assert store.get_checkout_order("order_hook")["payment_status"] == "captured"
