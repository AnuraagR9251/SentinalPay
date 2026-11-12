"""HOLD checkout uses the secondary assessment. Razorpay HTTP stays mocked."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from api.main import app
from api.tests.test_checkout import Fake, _body, _login
from risk import secondary
from risk.secondary import APPROVAL_TTL_S
from risk.store import get_store


def _hold_eval(monkeypatch, **extra):
    fake = Fake()

    def evaluate(raw, **_kwargs):
        result = {
            "transaction_id": raw["transaction_id"],
            "user_id": raw["user_id"],
            "action": "HOLD",
            "decision": "REVIEW",
            "risk_score": 44,
            "rules": {"triggered_rules": []},
            "ml": {"available": True, "fraud_probability": 0.2},
            "recent_failures": 0,
        }
        result.update(extra)
        return result

    monkeypatch.setattr("api.main.evaluate_transaction", evaluate)
    monkeypatch.setattr("api.main.get_razorpay_adapter", lambda: fake)
    return fake


def _seed_familiar(user: str = "aarav@senitenial") -> None:
    store = get_store()
    now = datetime.now(timezone.utc)
    with store._connect() as conn:
        for i in range(5):
            conn.execute(
                """
                INSERT INTO transactions (
                    transaction_id, user_id, amount, currency, merchant_id,
                    merchant_category, timestamp, device_id, latitude, longitude
                ) VALUES (?, ?, 1.0, 'INR', 'shop@upi', 'p2p', ?, 'dev-1', 12.97, 77.59)
                """,
                (f"hist-{i}", user, (now - timedelta(days=i + 1)).isoformat()),
            )
        conn.execute(
            """
            INSERT INTO checkout_orders (
                transaction_id, order_id, user_id, amount_paise, currency,
                payment_id, payment_status, created_at, updated_at
            ) VALUES ('hist-0', 'order_hist', ?, 100, 'INR', 'pay_hist', 'captured', ?, ?)
            """,
            (user, now.isoformat(), now.isoformat()),
        )
        conn.commit()


def _hold_body(**extra) -> dict:
    payload = _body(
        device_id="dev-1",
        latitude=12.97,
        longitude=77.59,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    payload.update(extra)
    return payload


def test_hold_then_secondary_approve_creates_an_unsettled_order(monkeypatch) -> None:
    fake = _hold_eval(monkeypatch)
    _seed_familiar()
    client = TestClient(app)
    posted = client.post("/api/create-order", json=_hold_body(transaction_id="tx-approve"))
    assert posted.status_code == 200
    body = posted.json()
    assert body["order_id"] == "order_1"
    assert body["secondary_outcome"] == "APPROVE"
    assert body["settled"] is False
    assert body["action"] == "HOLD"
    assert fake.creates == 1
    stored = get_store().get_secondary_assessment("tx-approve")
    assert stored["outcome"] == "APPROVE"
    assert stored["primary_decision"] == "REVIEW"


def test_hold_then_secondary_reject_creates_no_order(monkeypatch) -> None:
    fake = _hold_eval(monkeypatch, rules={"triggered_rules": [{"rule": "FAILED_ATTEMPTS"}]})
    _seed_familiar()
    client = TestClient(app)
    posted = client.post("/api/create-order", json=_hold_body(transaction_id="tx-reject"))
    assert posted.status_code == 403
    assert posted.json()["detail"]["secondary_outcome"] == "REJECT"
    assert fake.creates == 0
    assert get_store().get_checkout_by_transaction("tx-reject") is None
    assert get_store().get_secondary_assessment("tx-reject")["outcome"] == "REJECT"


def test_hold_without_history_continues_hold(monkeypatch) -> None:
    fake = _hold_eval(monkeypatch)
    client = TestClient(app)
    posted = client.post("/api/create-order", json=_hold_body(transaction_id="tx-thin"))
    assert posted.status_code == 403
    assert posted.json()["detail"]["secondary_outcome"] == "CONTINUE_HOLD"
    assert fake.creates == 0
    assert get_store().get_checkout_by_transaction("tx-thin") is None
    assert "missing_history" in get_store().get_secondary_assessment("tx-thin")["reasons"]


def test_unavailable_model_does_not_approve(monkeypatch) -> None:
    fake = _hold_eval(monkeypatch, ml={"available": False, "fraud_probability": 0.5})
    _seed_familiar()
    client = TestClient(app)
    posted = client.post("/api/create-order", json=_hold_body(transaction_id="tx-nomodel"))
    assert posted.status_code == 403
    assert posted.json()["detail"]["secondary_outcome"] == "CONTINUE_HOLD"
    assert fake.creates == 0
    reasons = get_store().get_secondary_assessment("tx-nomodel")["reasons"]
    assert "model_unavailable" in reasons
    assert "missing_history" not in reasons


def test_secondary_failure_fails_closed(monkeypatch) -> None:
    fake = _hold_eval(monkeypatch)
    _seed_familiar()

    def boom(_evidence):
        raise RuntimeError("secondary down")

    monkeypatch.setattr(secondary, "assess_secondary", boom)
    client = TestClient(app)
    posted = client.post("/api/create-order", json=_hold_body(transaction_id="tx-fail"))
    assert posted.status_code == 403
    assert posted.json()["detail"]["secondary_outcome"] == "CONTINUE_HOLD"
    assert fake.creates == 0
    assert get_store().get_secondary_assessment("tx-fail")["reasons"] == ["assessment_failed"]


def test_duplicate_hold_does_not_reassess_or_reorder(monkeypatch) -> None:
    fake = _hold_eval(monkeypatch)
    _seed_familiar()
    calls = {"n": 0}
    real = secondary.assess_secondary

    def wrapped(evidence):
        calls["n"] += 1
        return real(evidence)

    monkeypatch.setattr(secondary, "assess_secondary", wrapped)
    client = TestClient(app)
    body = _hold_body(transaction_id="tx-replay")
    first = client.post("/api/create-order", json=body)
    second = client.post("/api/create-order", json=body)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["order_id"] == first.json()["order_id"]
    assert fake.creates == 1
    assert calls["n"] == 1


def test_changed_details_after_approval_are_rejected(monkeypatch) -> None:
    fake = _hold_eval(monkeypatch)
    _seed_familiar()
    client = TestClient(app)
    approved = client.post("/api/create-order", json=_hold_body(transaction_id="tx-bind"))
    assert approved.status_code == 200
    changed = client.post(
        "/api/create-order",
        json=_hold_body(transaction_id="tx-bind", merchant_id="other@upi"),
    )
    assert changed.status_code == 409
    assert changed.json()["detail"] == "transaction details changed"
    assert fake.creates == 1
    assert get_store().get_secondary_assessment("tx-bind")["merchant_id"] == "shop@upi"


def test_client_cannot_submit_its_own_secondary_outcome(monkeypatch) -> None:
    fake = _hold_eval(monkeypatch)
    client = TestClient(app)
    posted = client.post(
        "/api/create-order",
        json=_hold_body(transaction_id="tx-bypass", secondary_outcome="APPROVE", action="ALLOW"),
    )
    assert posted.status_code == 403
    assert posted.json()["detail"]["secondary_outcome"] == "CONTINUE_HOLD"
    assert fake.creates == 0
    verify = client.post(
        "/api/verify-payment",
        json={
            "razorpay_order_id": "order_forged",
            "razorpay_payment_id": "pay_forged",
            "razorpay_signature": "forged",
            "transaction_id": "tx-bypass",
        },
    )
    assert verify.status_code == 400
    assert get_store().get_checkout_order("order_forged") is None


def test_graph_flag_on_hold_rejects_before_razorpay(monkeypatch) -> None:
    fake = _hold_eval(
        monkeypatch,
        experimental={
            "ae_available": True,
            "P_ae": 0.1,
            "graph_available": True,
            "structuring_flag": True,
            "mule_cluster": False,
            "P_graph": 0.4,
        },
    )
    _seed_familiar()
    client = TestClient(app)
    posted = client.post("/api/create-order", json=_hold_body(transaction_id="tx-graph"))
    assert posted.status_code == 403
    assert posted.json()["detail"]["secondary_outcome"] == "REJECT"
    assert fake.creates == 0
    assert get_store().get_checkout_by_transaction("tx-graph") is None


def test_autoencoder_flag_on_hold_requires_step_up_before_order(monkeypatch) -> None:
    fake = _hold_eval(
        monkeypatch,
        experimental={
            "ae_available": True,
            "P_ae": 1.0,
            "graph_available": True,
            "structuring_flag": False,
            "mule_cluster": False,
            "P_graph": 0.02,
        },
    )
    _seed_familiar()
    client = TestClient(app)
    denied = client.post("/api/create-order", json=_hold_body(transaction_id="tx-ae-step"))
    assert denied.status_code == 403
    detail = denied.json()["detail"]
    assert detail["action"] == "STEP_UP"
    assert detail["secondary_outcome"] == "STEP_UP"
    assert detail["challenge_id"]
    assert fake.creates == 0
    now = datetime.now(timezone.utc).isoformat()
    store = get_store()
    with store._connect() as conn:
        conn.execute(
            """
            UPDATE challenges
            SET consumed_at = ?
            WHERE challenge_id = ?
            """,
            (now, detail["challenge_id"]),
        )
        conn.commit()
    allowed = client.post("/api/create-order", json=_hold_body(transaction_id="tx-ae-step"))
    assert allowed.status_code == 200
    assert allowed.json()["secondary_outcome"] == "STEP_UP"
    assert allowed.json()["settled"] is False
    assert fake.creates == 1


def test_client_cannot_override_fusion_with_a_body_field(monkeypatch) -> None:
    fake = _hold_eval(
        monkeypatch,
        experimental={
            "ae_available": True,
            "P_ae": 0.1,
            "graph_available": True,
            "structuring_flag": True,
            "mule_cluster": False,
        },
    )
    _seed_familiar()
    client = TestClient(app)
    posted = client.post(
        "/api/create-order",
        json=_hold_body(transaction_id="tx-fuse-bypass", decision="ALLOW", secondary_outcome="APPROVE"),
    )
    assert posted.status_code == 403
    assert posted.json()["detail"]["secondary_outcome"] == "REJECT"
    assert fake.creates == 0


def test_expired_approval_is_not_renewed(monkeypatch) -> None:
    fake = _hold_eval(monkeypatch)
    _seed_familiar()
    store = get_store()
    store.put_secondary_assessment(
        {
            "transaction_id": "tx-expired",
            "user_id": "aarav@senitenial",
            "amount_paise": 100,
            "currency": "INR",
            "merchant_id": "shop@upi",
            "device_id": "dev-1",
            "latitude": 12.97,
            "longitude": 77.59,
            "outcome": "APPROVE",
            "reasons": ["history_consistent"],
            "primary_action": "HOLD",
            "primary_decision": "REVIEW",
            "primary_score": 44,
            "ttl_s": APPROVAL_TTL_S,
        }
    )
    past = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    with store._connect() as conn:
        conn.execute(
            "UPDATE secondary_assessments SET expires_at = ? WHERE transaction_id = ?",
            (past, "tx-expired"),
        )
        conn.commit()
    calls = {"n": 0}
    real = secondary.assess_secondary

    def wrapped(evidence):
        calls["n"] += 1
        return real(evidence)

    monkeypatch.setattr(secondary, "assess_secondary", wrapped)
    client = TestClient(app)
    posted = client.post("/api/create-order", headers=_login(client), json=_hold_body(transaction_id="tx-expired"))
    assert posted.status_code == 403
    assert posted.json()["detail"]["secondary_outcome"] == "CONTINUE_HOLD"
    assert fake.creates == 0
    assert calls["n"] == 0
    assert get_store().get_secondary_assessment("tx-expired")["outcome"] == "APPROVE"
