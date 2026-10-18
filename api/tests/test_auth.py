"""Phase 4 login and PIN on the existing FastAPI."""

from fastapi.testclient import TestClient

from api.main import app


def test_wrong_password_is_401() -> None:
    client = TestClient(app)
    posted = client.post("/login", json={"user_id": "aarav@senitenial", "password": "nope"})
    assert posted.status_code == 401


def test_login_then_score() -> None:
    client = TestClient(app)
    login = client.post("/login", json={"user_id": "aarav@senitenial", "password": "demo123"})
    assert login.status_code == 200
    token = login.json()["token"]
    scored = client.post(
        "/score",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "transaction_id": "auth-score-1",
            "amount": 250,
            "payee_vpa": "priya@oksbi",
            "user_id": "aarav@senitenial",
            "timestamp": "2026-09-28T11:00:00+00:00",
            "payer_location": {"lat": 12.9716, "lon": 77.5946},
            "is_new_payee": False,
            "purpose": "dining",
        },
    )
    assert scored.status_code == 200


def test_pin_verify_and_required_login(monkeypatch) -> None:
    monkeypatch.setenv("SENTINALPAY_REQUIRE_LOGIN", "1")
    client = TestClient(app)
    denied = client.post(
        "/score",
        json={
            "transaction_id": "auth-denied-1",
            "amount": 250,
            "payee_vpa": "priya@oksbi",
            "user_id": "aarav@senitenial",
            "timestamp": "2026-09-28T11:00:00+00:00",
            "payer_location": {"lat": 12.9716, "lon": 77.5946},
            "is_new_payee": False,
            "purpose": "dining",
        },
    )
    assert denied.status_code == 401
    login = client.post("/login", json={"user_id": "aarav@senitenial", "password": "demo123"})
    token = login.json()["token"]
    pin = client.post(
        "/pin/verify",
        headers={"Authorization": f"Bearer {token}"},
        json={"pin": "0000"},
    )
    assert pin.status_code == 401
    ok = client.post(
        "/pin/verify",
        headers={"Authorization": f"Bearer {token}"},
        json={"pin": "1234"},
    )
    assert ok.status_code == 200


def test_expired_session_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("SENTINALPAY_REQUIRE_LOGIN", "1")
    monkeypatch.setenv("SENTINALPAY_SESSION_TTL_SECONDS", "1")
    import time

    client = TestClient(app)
    login = client.post("/login", json={"user_id": "aarav@senitenial", "password": "demo123"})
    token = login.json()["token"]
    time.sleep(1.1)
    scored = client.post(
        "/score",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "transaction_id": "auth-expired-1",
            "amount": 250,
            "payee_vpa": "priya@oksbi",
            "user_id": "aarav@senitenial",
            "timestamp": "2026-09-28T11:00:00+00:00",
            "payer_location": {"lat": 12.9716, "lon": 77.5946},
            "is_new_payee": False,
            "purpose": "dining",
        },
    )
    assert scored.status_code == 401


def test_login_rate_limit(monkeypatch) -> None:
    client = TestClient(app)
    for _ in range(8):
        client.post("/login", json={"user_id": "aarav@senitenial", "password": "nope"})
    locked = client.post("/login", json={"user_id": "aarav@senitenial", "password": "nope"})
    assert locked.status_code == 429


def test_order_creation_is_not_anonymous() -> None:
    client = TestClient(app)
    posted = client.post("/payments/razorpay/orders", json={"amount": 10, "currency": "INR"})
    assert posted.status_code == 401


def test_feed_requires_session_when_login_on(monkeypatch) -> None:
    monkeypatch.setenv("SENTINALPAY_REQUIRE_LOGIN", "1")
    client = TestClient(app)
    denied = client.get("/transactions")
    assert denied.status_code == 401
    token = client.post("/login", json={"user_id": "aarav@senitenial", "password": "demo123"}).json()["token"]
    ok = client.get("/transactions", headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200


def test_challenge_requires_session_when_login_on(monkeypatch) -> None:
    monkeypatch.setenv("SENTINALPAY_REQUIRE_LOGIN", "1")
    client = TestClient(app)
    denied = client.post("/pin/verify", json={"pin": "1234", "challenge_id": "nope"})
    assert denied.status_code == 401
