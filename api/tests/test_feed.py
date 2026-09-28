"""Live feed: GET /transactions reads the canonical RiskStore."""

from fastapi.testclient import TestClient

from api.main import app


def test_transactions_starts_empty() -> None:
    client = TestClient(app)
    response = client.get("/transactions")
    assert response.status_code == 200
    assert response.json() == []


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
            "payer_location": {"lat": 18.5204, "lon": 73.8567},
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
    rows = feed.json()
    assert rows[0]["transaction_id"] == "tx-desk-1"
    assert rows[0]["purpose"] == "dining"
    assert "P_hybrid" in rows[0]


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
