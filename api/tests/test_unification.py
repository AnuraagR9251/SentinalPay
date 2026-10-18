"""Phase 1: one engine, one history, adapter-only translation."""

from fastapi.testclient import TestClient

from api.compat import legacy_fields_from_canonical
from api.main import app
from risk.store import get_store


def test_legacy_unknown_ml_does_not_claim_available() -> None:
    missing = legacy_fields_from_canonical(
        {
            "transaction_id": "tx-old",
            "decision": "ALLOW",
            "risk_score": 10,
        }
    )
    assert missing["ml_available"] is None
    assert missing["P_xgb"] is None

    partial = legacy_fields_from_canonical(
        {
            "transaction_id": "tx-partial",
            "decision": "ALLOW",
            "risk_score": 10,
            "ml": {"fraud_probability": 0.5},
        }
    )
    assert partial["ml_available"] is None
    assert partial["P_xgb"] is None

    down = legacy_fields_from_canonical(
        {
            "transaction_id": "tx-down",
            "decision": "REVIEW",
            "risk_score": 20,
            "ml": {"available": False, "fraud_probability": 0.5, "error": "missing_file"},
        }
    )
    assert down["ml_available"] is False
    assert down["P_xgb"] is None

    live = legacy_fields_from_canonical(
        {
            "transaction_id": "tx-live",
            "decision": "ALLOW",
            "risk_score": 12,
            "ml": {"available": True, "fraud_probability": 0.81},
        }
    )
    assert live["ml_available"] is True
    assert live["P_xgb"] == 0.81

    ae_down = legacy_fields_from_canonical(
        {
            "transaction_id": "tx-ae-down",
            "decision": "ALLOW",
            "risk_score": 12,
            "ml": {"available": True, "fraud_probability": 0.1},
            "experimental": {"ae_available": False, "P_ae": None, "ae_error": "missing_file"},
        }
    )
    assert ae_down["ae_available"] is False
    assert ae_down["P_ae"] is None

    ae_live = legacy_fields_from_canonical(
        {
            "transaction_id": "tx-ae-live",
            "decision": "ALLOW",
            "risk_score": 12,
            "ml": {"available": True, "fraud_probability": 0.1},
            "experimental": {"ae_available": True, "P_ae": 0.42, "graph_available": True, "P_graph": 0.2, "structuring_flag": False},
        }
    )
    assert ae_live["ae_available"] is True
    assert ae_live["P_ae"] == 0.42
    assert ae_live["graph_available"] is True
    assert ae_live["P_graph"] == 0.2
    assert ae_live["canonical_risk_score"] == 12


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
    if legacy["ae_available"]:
        assert legacy["P_ae"] is not None
        assert 0.0 <= legacy["P_ae"] <= 1.0
    else:
        assert legacy["P_ae"] is None
    if legacy["graph_available"]:
        assert legacy["P_graph"] is not None
        assert 0.0 <= legacy["P_graph"] <= 1.0
        assert legacy["structuring_flag"] in {True, False}
    else:
        assert legacy["P_graph"] is None
    assert legacy["ml_available"] == canonical["ml"]["available"]
    if canonical["ml"]["available"] is True:
        assert legacy["P_xgb"] == canonical["ml"]["fraud_probability"]
    else:
        assert legacy["P_xgb"] is None
    assert legacy["canonical_decision"] == canonical["decision"]
    assert legacy["canonical_risk_score"] == canonical["risk_score"]
    if canonical.get("action") == "STEP_UP":
        assert legacy["risk_tier"] == "STEP_UP"
        assert canonical["decision"] == "REVIEW"
    else:
        assert legacy["risk_tier"] == {"ALLOW": "ALLOW", "REVIEW": "HOLD", "BLOCK": "BLOCK"}[canonical["decision"]]


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


def test_reused_transaction_id_with_new_amount_is_409() -> None:
    client = TestClient(app)
    first = client.post(
        "/api/v1/transactions/evaluate",
        json={
            "transaction_id": "TXN_CONFLICT_1",
            "user_id": "USR_CONFLICT",
            "amount": 500.0,
            "currency": "INR",
            "merchant_id": "shop@oksbi",
            "merchant_category": "dining",
            "timestamp": "2026-09-28T11:00:00+00:00",
        },
    )
    assert first.status_code == 200
    original = first.json()
    conflicted = client.post(
        "/api/v1/transactions/evaluate",
        json={
            "transaction_id": "TXN_CONFLICT_1",
            "user_id": "USR_CONFLICT",
            "amount": 1500.0,
            "currency": "INR",
            "merchant_id": "shop@oksbi",
            "merchant_category": "dining",
            "timestamp": "2026-09-28T11:00:00+00:00",
        },
    )
    assert conflicted.status_code == 409
    assert "different payment details" in conflicted.json()["detail"]
    assert "risk_score" not in conflicted.json()
    replay = client.post(
        "/score",
        json={
            "transaction_id": "TXN_CONFLICT_1",
            "amount": 500.0,
            "payee_vpa": "shop@oksbi",
            "user_id": "USR_CONFLICT",
            "timestamp": "2026-09-28T11:00:00+00:00",
            "is_new_payee": False,
            "purpose": "dining",
        },
    )
    assert replay.status_code == 200
    assert replay.json()["canonical_risk_score"] == original["risk_score"]
