"""Phase 1: one engine, one history, adapter-only translation."""

from fastapi.testclient import TestClient

from api.main import app
from risk.store import get_store


def test_score_and_evaluate_share_pipeline() -> None:
    client = TestClient(app)
    payload = {
        "transaction_id": "TXN_SHARED_1",
        "user_id": "USR_SHARED",
        "amount": 1200.0,
        "currency": "INR",
        "merchant_id": "shop.blr@oksbi",
        "merchant_category": "dining",
        "timestamp": "2026-09-28T11:00:00+00:00",
        "latitude": 12.9716,
        "longitude": 77.5946,
    }
    evaluated = client.post("/api/v1/transactions/evaluate", json=payload)
    assert evaluated.status_code == 200
    canonical = evaluated.json()

    scored = client.post(
        "/score",
        json={
            "transaction_id": "TXN_SHARED_1",
            "amount": 1200.0,
            "payee_vpa": "shop.blr@oksbi",
            "user_id": "USR_SHARED",
            "timestamp": "2026-09-28T11:00:00+00:00",
            "payer_location": {"lat": 12.9716, "lon": 77.5946},
            "is_new_payee": False,
            "purpose": "dining",
        },
    )
    assert scored.status_code == 200
    legacy = scored.json()
    assert legacy["canonical_decision"] == canonical["decision"]
    assert legacy["canonical_risk_score"] == canonical["risk_score"]
    assert legacy["risk_tier"] == {"ALLOW": "ALLOW", "REVIEW": "HOLD", "BLOCK": "BLOCK"}[canonical["decision"]]
    assert legacy["risk_tier"] != "STEP_UP"


def test_history_is_shared_across_entrypoints() -> None:
    client = TestClient(app)
    first = client.post(
        "/score",
        json={
            "transaction_id": "TXN_HIST_A",
            "amount": 400.0,
            "payee_vpa": "merchant.a@oksbi",
            "user_id": "USR_HIST",
            "timestamp": "2026-09-28T09:00:00+00:00",
            "payer_location": {"lat": 12.9716, "lon": 77.5946},
            "is_new_payee": True,
            "purpose": "dining",
        },
    )
    assert first.status_code == 200
    second = client.post(
        "/api/v1/transactions/evaluate",
        json={
            "transaction_id": "TXN_HIST_B",
            "user_id": "USR_HIST",
            "amount": 410.0,
            "merchant_id": "merchant.b@oksbi",
            "merchant_category": "dining",
            "timestamp": "2026-09-28T09:10:00+00:00",
            "latitude": 12.9716,
            "longitude": 77.5946,
        },
    )
    assert second.status_code == 200
    names = {item["rule"] for item in second.json()["rules"]["triggered_rules"]}
    assert "NEW_MERCHANT" in names
    assert get_store().count_transactions("USR_HIST") == 2
