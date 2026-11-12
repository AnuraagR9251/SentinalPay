"""Fraud-desk admin cookie. Payer bearer sessions stay on /login."""

import time

from fastapi.testclient import TestClient

from api.main import app
from api.tests.desk_auth import CSRF, DESK_PASSWORD, DESK_USER, sign_in_desk

SCORE_MUTATION = """
mutation Score($input: ScoreInput!) {
  scoreTransaction(input: $input) { transactionId }
}
"""


def _score_vars() -> dict:
    return {
        "input": {
            "transactionId": "admin-gql-score",
            "amount": 240.0,
            "payeeVpa": "kirana.lab@oksbi",
            "userId": "aarav@senitenial",
            "timestamp": "2026-09-28T11:00:00+00:00",
            "isNewPayee": False,
            "purpose": "groceries",
        }
    }


def test_health_stays_public() -> None:
    client = TestClient(app)
    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200


def test_unauthenticated_desk_is_rejected() -> None:
    client = TestClient(app)
    assert client.get("/transactions").status_code == 401
    assert client.get("/admin/session").status_code == 401
    assert client.get("/api/v1/reviews").status_code == 401
    denied = client.post("/graphql", json={"query": "query { transactions { transactionId } }"})
    assert denied.json().get("errors")


def test_valid_admin_login_sets_cookie_and_opens_desk() -> None:
    client = TestClient(app)
    logged = sign_in_desk(client)
    header = logged.headers["set-cookie"].lower()
    assert "httponly" in header
    assert "samesite=lax" in header
    assert "secure" not in header
    assert DESK_PASSWORD not in header
    session = client.get("/admin/session")
    assert session.status_code == 200
    assert session.json() == {"username": DESK_USER}
    assert client.get("/transactions").status_code == 200


def test_invalid_password_and_unknown_username_match() -> None:
    client = TestClient(app)
    bad_password = client.post(
        "/admin/login",
        json={"username": DESK_USER, "password": "wrong-password"},
    )
    bad_user = client.post(
        "/admin/login",
        json={"username": "nobody", "password": "wrong-password"},
    )
    assert bad_password.status_code == 401
    assert bad_user.status_code == 401
    assert bad_password.json() == bad_user.json()
    assert bad_password.json()["detail"] == "invalid credentials"
    assert "wrong-password" not in bad_password.text


def test_expired_admin_session_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("SENTINALPAY_ADMIN_SESSION_TTL_SECONDS", "1")
    client = TestClient(app)
    sign_in_desk(client)
    time.sleep(1.1)
    assert client.get("/admin/session").status_code == 401
    assert client.get("/transactions").status_code == 401


def test_logout_revokes_desk_session() -> None:
    client = TestClient(app)
    sign_in_desk(client)
    blocked = client.post("/admin/logout")
    assert blocked.status_code == 403
    assert client.get("/admin/session").status_code == 200
    logged_out = client.post("/admin/logout", headers=CSRF)
    assert logged_out.status_code == 200
    assert client.get("/admin/session").status_code == 401
    assert client.get("/transactions").status_code == 401


def test_demo_bearer_cannot_open_desk_or_score_as_admin(monkeypatch) -> None:
    monkeypatch.setenv("SENTINALPAY_REQUIRE_LOGIN", "1")
    client = TestClient(app)
    token = client.post("/login", json={"user_id": "aarav@senitenial", "password": "demo123"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/transactions", headers=headers).status_code == 401
    sign_in_desk(client)
    scored = client.post(
        "/graphql",
        json={"query": SCORE_MUTATION, "variables": _score_vars()},
    )
    assert scored.json().get("errors")
    assert scored.json().get("data") is None or scored.json()["data"]["scoreTransaction"] is None


def test_review_post_requires_csrf() -> None:
    client = TestClient(app)
    sign_in_desk(client)
    posted = client.post(
        "/api/v1/reviews/missing",
        json={"decision": "APPROVED", "reason": "desk"},
    )
    assert posted.status_code == 403
    posted_ok = client.post(
        "/api/v1/reviews/missing",
        headers=CSRF,
        json={"decision": "APPROVED", "reason": "desk"},
    )
    assert posted_ok.status_code == 404


def test_repeated_admin_login_failures_lock(monkeypatch) -> None:
    client = TestClient(app)
    for _ in range(8):
        failed = client.post("/admin/login", json={"username": DESK_USER, "password": "nope"})
        assert failed.status_code == 401
    locked = client.post("/admin/login", json={"username": DESK_USER, "password": DESK_PASSWORD})
    assert locked.status_code == 429


def test_secure_cookie_flag_follows_env(monkeypatch) -> None:
    monkeypatch.setenv("SENTINALPAY_COOKIE_SECURE", "1")
    client = TestClient(app)
    logged = sign_in_desk(client)
    assert "secure" in logged.headers["set-cookie"].lower()
