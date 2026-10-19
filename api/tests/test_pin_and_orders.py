"""PIN throttle, challenge binding, and order/webhook input hardening."""

from fastapi.testclient import TestClient

from api.main import app
from risk.store import get_store


def _pin_gql(client, pin: str, challenge_id: str | None = None, headers: dict | None = None):
    cid = f', challengeId: "{challenge_id}"' if challenge_id else ""
    return client.post(
        "/graphql",
        headers=headers or {},
        json={"query": f'mutation {{ verifyPin(pin: "{pin}"{cid}) {{ ok error }} }}'},
    )


def test_graphql_wrong_pin_returns_payload() -> None:
    client = TestClient(app)
    store = get_store()
    cid = store.create_challenge("aarav@senitenial", "chal-msg-1", None, max_attempts=3)["challenge_id"]
    gql = _pin_gql(client, "0000", cid)
    body = gql.json()
    assert not body.get("errors")
    assert body["data"]["verifyPin"]["ok"] is False
    assert body["data"]["verifyPin"]["error"] == "invalid_pin"


def test_graphql_third_wrong_pin_locks() -> None:
    client = TestClient(app)
    store = get_store()
    cid = store.create_challenge("aarav@senitenial", "chal-lock-1", None, max_attempts=3)["challenge_id"]
    first = _pin_gql(client, "0000", cid).json()["data"]["verifyPin"]
    second = _pin_gql(client, "0000", cid).json()["data"]["verifyPin"]
    third = _pin_gql(client, "0000", cid).json()["data"]["verifyPin"]
    assert first["error"] == "invalid_pin"
    assert second["error"] == "invalid_pin"
    assert third["ok"] is False
    assert third["error"] == "locked"


def test_open_sandbox_pin_without_session() -> None:
    client = TestClient(app)
    bad = client.post("/pin/verify", json={"pin": "0000"})
    assert bad.status_code == 401
    assert bad.json()["detail"] == "invalid pin"
    good = client.post("/pin/verify", json={"pin": "1234"})
    assert good.status_code == 200
    assert good.json()["ok"] is True


def test_standalone_pin_throttle_shared_with_graphql() -> None:
    client = TestClient(app)
    token = client.post("/login", json={"user_id": "aarav@senitenial", "password": "demo123"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    for _ in range(8):
        client.post("/pin/verify", headers=headers, json={"pin": "0000"})
    locked = client.post("/pin/verify", headers=headers, json={"pin": "0000"})
    assert locked.status_code == 429
    gql = _pin_gql(client, "0000", headers=headers)
    body = gql.json()
    assert not body.get("errors")
    assert body["data"]["verifyPin"]["ok"] is False
    assert body["data"]["verifyPin"]["error"] == "locked"


def test_challenge_caps_and_replay_on_both_routes() -> None:
    client = TestClient(app)
    store = get_store()
    challenge = store.create_challenge("aarav@senitenial", "chal-http-1", None, max_attempts=3)
    cid = challenge["challenge_id"]
    for _ in range(3):
        bad = client.post("/pin/verify", json={"pin": "0000", "challenge_id": cid})
        assert bad.status_code == 401
    gql = _pin_gql(client, "1234", cid)
    body = gql.json()
    assert not body.get("errors")
    assert body["data"]["verifyPin"]["ok"] is False
    assert body["data"]["verifyPin"]["error"] == "locked"


def test_challenge_session_mismatch_and_expiry() -> None:
    store = get_store()
    bound = store.create_challenge("aarav@senitenial", "chal-sess-1", "session-alpha", max_attempts=3)
    mismatch = store.verify_challenge(
        bound["challenge_id"],
        user_id="aarav@senitenial",
        session_token="session-beta",
        pin="1234",
    )
    assert mismatch["ok"] is False
    assert mismatch["error"] == "session_mismatch"
    expired = store.create_challenge("aarav@senitenial", "chal-exp-1", None, ttl_seconds=-1, max_attempts=3)
    outcome = store.verify_challenge(
        expired["challenge_id"],
        user_id="aarav@senitenial",
        session_token=None,
        pin="1234",
    )
    assert outcome["ok"] is False
    assert outcome["error"] == "expired"


def test_challenge_user_mismatch() -> None:
    store = get_store()
    row = store.create_challenge("aarav@senitenial", "chal-user-1", None)
    other = store.verify_challenge(row["challenge_id"], user_id="priya@senitenial", session_token=None, pin="1234")
    assert other["ok"] is False
    assert other["error"] == "user_mismatch"


def test_order_rejects_bad_input(monkeypatch) -> None:
    monkeypatch.setenv("RAZORPAY_KEY_ID", "")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "")
    from payments.razorpay import get_razorpay_adapter

    adapter = get_razorpay_adapter()
    monkeypatch.setattr(adapter, "key_id", "")
    monkeypatch.setattr(adapter, "key_secret", "")
    client = TestClient(app)
    monkey_login = client.post("/login", json={"user_id": "aarav@senitenial", "password": "demo123"})
    token = monkey_login.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.post("/payments/razorpay/orders", json={"amount": 10, "currency": "INR"}).status_code == 401
    assert (
        client.post(
            "/payments/razorpay/orders",
            headers=headers,
            json={"amount": 0, "currency": "INR"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/payments/razorpay/orders",
            headers=headers,
            json={"amount": 10, "currency": "USD"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/payments/razorpay/orders",
            headers=headers,
            json={"amount": "NaN", "currency": "INR"},
        ).status_code
        == 422
    )
    long_id = "x" * 200
    assert (
        client.post(
            "/payments/razorpay/orders",
            headers=headers,
            json={"amount": 10, "currency": "INR", "transaction_id": long_id},
        ).status_code
        == 422
    )
    missing_keys = client.post(
        "/payments/razorpay/orders",
        headers=headers,
        json={"amount": 10, "currency": "INR", "transaction_id": "ord-1"},
    )
    assert missing_keys.status_code == 503
    assert missing_keys.json()["detail"] == "razorpay not configured"


def test_webhook_rejects_oversized_body(monkeypatch) -> None:
    from payments.razorpay import get_razorpay_adapter

    monkeypatch.setattr(get_razorpay_adapter(), "webhook_secret", "whsec")
    monkeypatch.setenv("SENTINALPAY_WEBHOOK_MAX_BYTES", "1024")
    client = TestClient(app)
    posted = client.post(
        "/webhooks/razorpay",
        content=b"{" + (b"a" * 2000) + b"}",
        headers={"X-Razorpay-Signature": "x"},
    )
    assert posted.status_code == 413
