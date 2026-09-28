"""Live feed: GET /transactions is the desk's source of truth."""

from fastapi.testclient import TestClient

from api.main import MODEL, SCORED_FEED, app


def test_transactions_starts_empty() -> None:
    SCORED_FEED.clear()
    client = TestClient(app)
    response = client.get("/transactions")
    assert response.status_code == 200
    assert response.json() == []


def test_score_then_feed_roundtrip() -> None:
    if MODEL is None:
        return
    SCORED_FEED.clear()
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
    feed = client.get("/transactions")
    assert feed.status_code == 200
    rows = feed.json()
    assert rows[0]["transaction_id"] == "tx-desk-1"
    assert rows[0]["purpose"] == "Dining"
    assert "P_hybrid" in rows[0]
