"""Live feed: GET /transactions reads the canonical RiskStore."""

import json
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from api.main import _feed_item, app


def test_transactions_starts_empty() -> None:
    client = TestClient(app)
    response = client.get("/transactions")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 0
    assert body["items"] == []
    assert body["sandbox"] is True


def test_score_then_feed_roundtrip() -> None:
    client = TestClient(app)
    posted = client.post(
        "/score",
        json={
            "transaction_id": "tx-desk-1",
            "amount": 240.0,
            "payee_vpa": "priya.p@oksbi",
            "user_id": "aarav@senitenial",
            "timestamp": "2026-09-28T10:00:00+00:00",
            "payer_location": {"lat": 12.9716, "lon": 77.5946},
            "is_new_payee": False,
            "purpose": "Dining",
        },
    )
    assert posted.status_code == 200
    body = posted.json()
    assert body["risk_tier"] in {"ALLOW", "STEP_UP", "HOLD", "BLOCK"}
    assert "canonical_decision" in body
    feed = client.get("/transactions")
    assert feed.status_code == 200
    body = feed.json()
    assert body["count"] == 1
    case = body["items"][0]
    assert case["payment"]["id"] == "tx-desk-1"
    assert case["payment"]["purpose"] == "dining"
    assert case["payment"]["user_id"] == "aarav@senitenial"
    assert case["canonical"]["decision"] in {"ALLOW", "REVIEW", "BLOCK"}
    assert 0 <= case["canonical"]["risk_score"] <= 100
    assert case["canonical"]["scale"] == "0-100"
    assert case["policy"]["legacy_tier"] in {"ALLOW", "STEP_UP", "HOLD", "BLOCK"}
    assert 0.0 <= case["policy"]["legacy_score"] <= 1.0
    ae = case["models"]["autoencoder"]
    graph = case["models"]["graph"]
    if ae["available"]:
        assert ae["value"] is not None
        assert 0.0 <= float(ae["value"]) <= 1.0
    else:
        assert ae["value"] is None
    if graph["available"]:
        assert graph["value"] is not None
        assert 0.0 <= float(graph["value"]) <= 1.0
    else:
        assert graph["value"] is None
    assert case["payment"]["location"]["status"] == "provided"
    xgb = case["models"]["xgboost"]
    assert xgb["available"] is posted.json()["ml_available"]
    if xgb["available"] is True:
        assert isinstance(xgb["value"], (int, float))
    else:
        assert xgb["value"] is None
        assert xgb["available"] in (False, None)


def test_evaluate_endpoint() -> None:
    client = TestClient(app)
    posted = client.post(
        "/api/v1/transactions/evaluate",
        json={
            "transaction_id": "TXN_API_1",
            "user_id": "USR_123",
            "amount": 8500.0,
            "currency": "INR",
            "merchant_id": "MERCHANT_456",
            "merchant_category": "electronics",
            "timestamp": "2026-09-28T10:30:00Z",
            "device_id": "DEV_789",
            "ip_address": "192.168.1.10",
            "latitude": 12.9716,
            "longitude": 77.5946,
        },
    )
    assert posted.status_code == 200
    body = posted.json()
    assert body["decision"] in {"ALLOW", "REVIEW", "BLOCK"}
    assert 0 <= body["risk_score"] <= 100
    assert "triggered_rules" in body["rules"]
    names = {item["rule"] for item in body["rules"]["triggered_rules"]}
    assert "HIGH_RISK_MERCHANT" not in names


def _row(result: dict) -> dict:
    return {
        "transaction_id": result["transaction_id"],
        "user_id": "aarav@senitenial",
        "amount": 240.0,
        "merchant_id": "priya.p@oksbi",
        "merchant_category": "dining",
        "timestamp": datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc),
        "latitude": 12.9716,
        "longitude": 77.5946,
        "result_json": json.dumps(result),
    }


def test_feed_item_experimental_ae_graph() -> None:
    case = _feed_item(
        _row(
            {
                "transaction_id": "tx-ae-yes",
                "risk_score": 12,
                "decision": "ALLOW",
                "ml": {"available": True, "fraud_probability": 0.1, "model_version": "xgb_v3"},
                "rules": {"triggered_rules": []},
                "experimental": {
                    "ae_available": True,
                    "P_ae": 0.33,
                    "graph_available": True,
                    "P_graph": 0.12,
                    "structuring_flag": False,
                    "note": "experimental; not blended",
                },
            }
        )
    )
    assert case.models.autoencoder.available is True
    assert case.models.autoencoder.value == 0.33
    assert case.models.graph.available is True
    assert case.models.graph.value == 0.12
    assert case.canonical.decision == "ALLOW"


def test_feed_item_marks_genuine_model_available() -> None:
    case = _feed_item(
        _row(
            {
                "transaction_id": "tx-ml-yes",
                "risk_score": 12,
                "decision": "ALLOW",
                "ml": {"available": True, "fraud_probability": 0.81, "model_version": "xgb_v3"},
                "rules": {"triggered_rules": []},
            }
        )
    )
    xgb = case.models.xgboost
    assert xgb.available is True
    assert xgb.value == 0.81
    assert xgb.note == "PaySim-trained; not a UPI-calibrated probability"

    calibrated = _feed_item(
        _row(
            {
                "transaction_id": "tx-ml-cal",
                "risk_score": 12,
                "decision": "ALLOW",
                "ml": {
                    "available": True,
                    "fraud_probability": 0.81,
                    "model_version": "xgb_v4",
                    "calibrated_for_upi": True,
                },
                "rules": {"triggered_rules": []},
            }
        )
    )
    assert calibrated.models.xgboost.available is True
    assert calibrated.models.xgboost.value == 0.81
    assert calibrated.models.xgboost.note is None


def test_feed_item_unavailable_model_hides_fallback_prior() -> None:
    case = _feed_item(
        _row(
            {
                "transaction_id": "tx-ml-no",
                "risk_score": 20,
                "decision": "REVIEW",
                "ml": {
                    "available": False,
                    "fraud_probability": 0.5,
                    "model_version": "unavailable",
                    "error": "missing_file",
                },
                "rules": {"triggered_rules": []},
            }
        )
    )
    xgb = case.models.xgboost
    assert xgb.available is False
    assert xgb.value is None
    assert "fallback prior" in (xgb.note or "")
    assert case.canonical.decision == "REVIEW"


def test_feed_item_unknown_availability_is_null() -> None:
    case = _feed_item(
        _row(
            {
                "transaction_id": "tx-ml-old",
                "risk_score": 10,
                "decision": "ALLOW",
                "rules": {"triggered_rules": []},
            }
        )
    )
    xgb = case.models.xgboost
    assert xgb.available is None
    assert xgb.value is None
    assert "unknown" in (xgb.note or "")


def test_feed_item_missing_available_key_is_null() -> None:
    case = _feed_item(
        _row(
            {
                "transaction_id": "tx-ml-partial",
                "risk_score": 10,
                "decision": "ALLOW",
                "ml": {"fraud_probability": 0.5, "model_version": "xgb_v3"},
                "rules": {"triggered_rules": []},
            }
        )
    )
    xgb = case.models.xgboost
    assert xgb.available is None
    assert xgb.value is None
    assert "unknown" in (xgb.note or "")
