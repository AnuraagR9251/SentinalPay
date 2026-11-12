"""Review queue and Razorpay order auth vs REQUIRE_LOGIN / API key."""

from fastapi.testclient import TestClient

from api.main import app
from api.tests.desk_auth import CSRF, sign_in_desk


def _login(client: TestClient) -> str:
    return client.post("/login", json={"user_id": "aarav@senitenial", "password": "demo123"}).json()["token"]


def _eval(client: TestClient, txn_id: str, headers: dict | None = None):
    return client.post(
        "/api/v1/transactions/evaluate",
        headers=headers or {},
        json={
            "transaction_id": txn_id,
            "user_id": "aarav@senitenial",
            "amount": 8500,
            "merchant_id": "stranger@oksbi",
            "merchant_category": "gambling",
            "device_id": "dev-new-review",
        },
    )


def test_reviews_require_admin_cookie() -> None:
    client = TestClient(app)
    assert client.get("/api/v1/reviews").status_code == 401
    missing = client.post(
        "/api/v1/reviews/no-such-txn",
        json={"decision": "APPROVED", "reason": "sandbox"},
    )
    assert missing.status_code == 401
    sign_in_desk(client)
    listed = client.get("/api/v1/reviews")
    assert listed.status_code == 200
    assert isinstance(listed.json(), list)
    no_csrf = client.post(
        "/api/v1/reviews/no-such-txn",
        json={"decision": "APPROVED", "reason": "sandbox"},
    )
    assert no_csrf.status_code == 403
    missing_ok = client.post(
        "/api/v1/reviews/no-such-txn",
        headers=CSRF,
        json={"decision": "APPROVED", "reason": "sandbox"},
    )
    assert missing_ok.status_code == 404


def test_reviews_ignore_demo_bearer(monkeypatch) -> None:
    monkeypatch.setenv("SENTINALPAY_REQUIRE_LOGIN", "1")
    monkeypatch.setenv("SENTINALPAY_DECIDE_ALLOW_MAX", "0")
    monkeypatch.setenv("SENTINALPAY_DECIDE_REVIEW_MAX", "100")
    payer = TestClient(app)
    token = _login(payer)
    payer_headers = {"Authorization": f"Bearer {token}"}
    assert payer.get("/api/v1/reviews", headers=payer_headers).status_code == 401
    evaluated = _eval(payer, "rev-auth-1", payer_headers)
    assert evaluated.status_code == 200
    desk = TestClient(app)
    sign_in_desk(desk)
    listed = desk.get("/api/v1/reviews")
    assert listed.status_code == 200
    submitted = desk.post(
        f"/api/v1/reviews/{evaluated.json()['transaction_id']}",
        headers=CSRF,
        json={"decision": "APPROVED", "reason": "desk admin"},
    )
    if evaluated.json()["decision"] == "REVIEW":
        assert submitted.status_code == 200
        assert submitted.json()["status"] == "APPROVED"
    else:
        assert submitted.status_code == 404


def test_reviews_demo_user_cannot_operate_queue(monkeypatch) -> None:
    monkeypatch.setenv("SENTINALPAY_REQUIRE_LOGIN", "1")
    client = TestClient(app)
    priya = client.post("/login", json={"user_id": "priya@senitenial", "password": "demo123"}).json()["token"]
    headers = {"Authorization": f"Bearer {priya}"}
    assert client.get("/api/v1/reviews", headers=headers).status_code == 401
    assert (
        client.post(
            "/api/v1/reviews/any",
            headers=headers,
            json={"decision": "APPROVED", "reason": "other demo user"},
        ).status_code
        == 401
    )


def test_reviews_need_key_and_admin_cookie(monkeypatch) -> None:
    monkeypatch.setenv("SENTINALPAY_REQUIRE_LOGIN", "1")
    monkeypatch.setenv("SENTINALPAY_API_KEY", "lab-secret")
    client = TestClient(app)
    token = _login(client)
    assert client.get("/api/v1/reviews").status_code == 401
    assert client.get("/api/v1/reviews", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert client.get("/api/v1/reviews", headers={"X-API-Key": "lab-secret"}).status_code == 401
    sign_in_desk(client)
    both = {"Authorization": f"Bearer {token}", "X-API-Key": "lab-secret"}
    assert client.get("/api/v1/reviews", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert client.get("/api/v1/reviews", headers=both).status_code == 200


def test_orders_login_on_requires_session(monkeypatch) -> None:
    monkeypatch.setenv("SENTINALPAY_REQUIRE_LOGIN", "1")
    monkeypatch.setenv("RAZORPAY_KEY_ID", "")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "")
    from payments.razorpay import get_razorpay_adapter

    adapter = get_razorpay_adapter()
    monkeypatch.setattr(adapter, "key_id", "")
    monkeypatch.setattr(adapter, "key_secret", "")
    client = TestClient(app)
    body = {"amount": 10, "currency": "INR", "transaction_id": "ord-login-1"}
    assert client.post("/payments/razorpay/orders", json=body).status_code == 401
    assert (
        client.post(
            "/payments/razorpay/orders",
            headers={"Authorization": "Bearer not-a-session"},
            json=body,
        ).status_code
        == 401
    )
    token = _login(client)
    posted = client.post(
        "/payments/razorpay/orders",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
    )
    assert posted.status_code == 503
    assert posted.json()["detail"] == "razorpay not configured"


def test_orders_login_on_api_key_still_needs_session(monkeypatch) -> None:
    monkeypatch.setenv("SENTINALPAY_REQUIRE_LOGIN", "1")
    monkeypatch.setenv("SENTINALPAY_API_KEY", "lab-secret")
    monkeypatch.setenv("RAZORPAY_KEY_ID", "")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "")
    from payments.razorpay import get_razorpay_adapter

    adapter = get_razorpay_adapter()
    monkeypatch.setattr(adapter, "key_id", "")
    monkeypatch.setattr(adapter, "key_secret", "")
    client = TestClient(app)
    body = {"amount": 10, "currency": "INR", "transaction_id": "ord-both-1"}
    assert client.post("/payments/razorpay/orders", json=body).status_code == 401
    key_only = client.post(
        "/payments/razorpay/orders",
        headers={"X-API-Key": "lab-secret"},
        json=body,
    )
    assert key_only.status_code == 401
    token = _login(client)
    session_only = client.post(
        "/payments/razorpay/orders",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
    )
    assert session_only.status_code == 401
    both = client.post(
        "/payments/razorpay/orders",
        headers={"Authorization": f"Bearer {token}", "X-API-Key": "lab-secret"},
        json=body,
    )
    assert both.status_code == 503


def test_orders_api_key_only_when_login_off(monkeypatch) -> None:
    monkeypatch.setenv("SENTINALPAY_REQUIRE_LOGIN", "0")
    monkeypatch.setenv("SENTINALPAY_API_KEY", "lab-secret")
    monkeypatch.setenv("RAZORPAY_KEY_ID", "")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "")
    from payments.razorpay import get_razorpay_adapter

    adapter = get_razorpay_adapter()
    monkeypatch.setattr(adapter, "key_id", "")
    monkeypatch.setattr(adapter, "key_secret", "")
    client = TestClient(app)
    body = {"amount": 10, "currency": "INR", "transaction_id": "ord-s2s-1"}
    assert client.post("/payments/razorpay/orders", json=body).status_code == 401
    ok = client.post(
        "/payments/razorpay/orders",
        headers={"X-API-Key": "lab-secret"},
        json=body,
    )
    assert ok.status_code == 503
    assert ok.json()["detail"] == "razorpay not configured"
