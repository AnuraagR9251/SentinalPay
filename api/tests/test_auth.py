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
