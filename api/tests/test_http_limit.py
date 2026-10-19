"""HTTP 429 is separate from payment-velocity fraud scoring."""

from fastapi.testclient import TestClient

from api.main import app


def test_http_limit_returns_429(monkeypatch) -> None:
    monkeypatch.setenv("SENTINALPAY_HTTP_RATE_LIMIT_PER_MIN", "3")
    monkeypatch.setenv("SENTINALPAY_API_KEY", "")
    client = TestClient(app)
    headers = {"X-API-Key": "client-a"}
    statuses = []
    for i in range(4):
        posted = client.post(
            "/score",
            headers=headers,
            json={
                "transaction_id": f"http-lim-{i}",
                "amount": 120,
                "payee_vpa": "shop@oksbi",
                "user_id": "USR_HTTP",
                "timestamp": "2026-09-28T11:00:00+00:00",
                "payer_location": {"lat": 12.9716, "lon": 77.5946},
                "is_new_payee": False,
                "purpose": "dining",
            },
        )
        statuses.append(posted.status_code)
    assert statuses[:3] == [200, 200, 200]
    assert statuses[3] == 429
    assert posted.headers.get("retry-after") == "60"


def test_http_limits_are_per_client_key(monkeypatch) -> None:
    monkeypatch.setenv("SENTINALPAY_HTTP_RATE_LIMIT_PER_MIN", "2")
    monkeypatch.setenv("SENTINALPAY_API_KEY", "")
    client = TestClient(app)
    body = {
        "amount": 120,
        "payee_vpa": "shop@oksbi",
        "user_id": "USR_HTTP2",
        "timestamp": "2026-09-28T11:00:00+00:00",
        "payer_location": {"lat": 12.9716, "lon": 77.5946},
        "is_new_payee": False,
        "purpose": "dining",
    }
    for i in range(3):
        client.post("/score", headers={"X-API-Key": "alpha"}, json={**body, "transaction_id": f"http-a-{i}"})
    blocked = client.post("/score", headers={"X-API-Key": "alpha"}, json={**body, "transaction_id": "http-a-x"})
    other = client.post("/score", headers={"X-API-Key": "beta"}, json={**body, "transaction_id": "http-b-1"})
    assert blocked.status_code == 429
    assert other.status_code == 200
