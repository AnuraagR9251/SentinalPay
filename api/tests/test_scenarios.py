"""Phase 3 lab scenarios against the live /score contract."""

from fastapi.testclient import TestClient

from api.main import app


def _score(client: TestClient, **overrides):
    body = {
        "transaction_id": "lab-default",
        "amount": 240.0,
        "payee_vpa": "kirana.lab@oksbi",
        "user_id": "USR_LAB",
        "timestamp": "2026-09-28T10:00:00+00:00",
        "payer_location": {"lat": 12.9716, "lon": 77.5946},
        "device_id": "dev-lab-1",
        "is_new_payee": False,
        "purpose": "groceries",
    }
    body.update(overrides)
    return client.post("/score", json=body)


def test_score_response_shape() -> None:
    client = TestClient(app)
    posted = _score(client, transaction_id="lab-shape-1")
    assert posted.status_code == 200
    body = posted.json()
    assert "risk_tier" in body
    assert "risk_score" in body
    assert "action_required" in body
    assert body["canonical_decision"] in {"ALLOW", "REVIEW", "BLOCK"}
    assert 0.0 <= body["risk_score"] <= 1.0
    assert 0 <= body["canonical_risk_score"] <= 100
    assert abs(body["risk_score"] - body["canonical_risk_score"] / 100.0) < 1e-9
    assert body.get("ml_calibrated_for_upi") is False
    assert body.get("ml_evaluation") == "synthetic_paysim"
    assert set(body.get("score_components") or {}) == {"rules", "behavior", "ml", "security"}
    assert "ae" not in (body.get("score_components") or {})
    assert body.get("action") in {"ALLOW", "REVIEW", "STEP_UP", "BLOCK"}
    if body["ae_available"]:
        assert body["P_ae"] is not None
        assert 0.0 <= body["P_ae"] <= 1.0
    else:
        assert body["P_ae"] is None
    if body["graph_available"]:
        assert body["P_graph"] is not None
        assert 0.0 <= body["P_graph"] <= 1.0
    else:
        assert body["P_graph"] is None


def test_score_graph_available_on_api() -> None:
    client = TestClient(app)
    posted = _score(client, transaction_id="lab-graph-1", user_id="USR_GRAPH_API")
    assert posted.status_code == 200
    body = posted.json()
    assert body["graph_available"] is True
    assert body["P_graph"] is not None
    assert 0.0 <= body["P_graph"] <= 1.0
    if not body["ae_available"]:
        assert body["P_ae"] is None


def test_grocery_unknown_location_baseline() -> None:
    client = TestClient(app)
    posted = _score(client, transaction_id="lab-groc-1", user_id="USR_LAB_NEW")
    assert posted.status_code == 200
    evaluated = client.post(
        "/api/v1/transactions/evaluate",
        json={
            "transaction_id": "lab-groc-eval",
            "user_id": "USR_LAB_NEW2",
            "amount": 240,
            "merchant_id": "kirana.lab@oksbi",
            "merchant_category": "groceries",
            "timestamp": "2026-09-28T10:00:00+00:00",
            "latitude": 12.9716,
            "longitude": 77.5946,
        },
    )
    assert evaluated.status_code == 200
    assert evaluated.json()["location_baseline"] == "UNKNOWN"


def test_replay_same_id_is_idempotent() -> None:
    client = TestClient(app)
    first = _score(client, transaction_id="lab-replay-1")
    second = _score(client, transaction_id="lab-replay-1")
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["canonical_risk_score"] == second.json()["canonical_risk_score"]
    assert first.json()["canonical_decision"] == second.json()["canonical_decision"]
    feed = client.get("/transactions")
    ids = [row["payment"]["id"] for row in feed.json()["items"] if row["payment"]["id"] == "lab-replay-1"]
    assert ids == ["lab-replay-1"]


def test_score_without_location_does_not_invent_coords() -> None:
    client = TestClient(app)
    posted = _score(client, transaction_id="lab-noloc-1", payer_location=None)
    assert posted.status_code == 200
    body = posted.json()
    assert body["transaction_id"] == "lab-noloc-1"
    assert body["canonical_decision"] in {"ALLOW", "REVIEW", "BLOCK"}
    if body["ae_available"]:
        assert 0.0 <= body["P_ae"] <= 1.0
    else:
        assert body["P_ae"] is None
    feed = client.get("/transactions")
    row = next(item for item in feed.json()["items"] if item["payment"]["id"] == "lab-noloc-1")
    assert row["payment"]["location"]["status"] == "omitted"
    assert row["payment"]["location"]["lat"] is None
    assert row["payment"]["location"]["lon"] is None


def test_new_payee_can_request_step_up() -> None:
    client = TestClient(app)
    client.post(
        "/api/v1/transactions/evaluate",
        json={
            "transaction_id": "lab-hist-1",
            "user_id": "USR_STEP",
            "amount": 300,
            "merchant_id": "known.lab@oksbi",
            "merchant_category": "dining",
            "timestamp": "2026-09-28T09:00:00+00:00",
            "latitude": 12.9716,
            "longitude": 77.5946,
        },
    )
    posted = _score(
        client,
        transaction_id="lab-newpay-1",
        user_id="USR_STEP",
        amount=48000,
        payee_vpa="stranger.lab@oksbi",
        purpose="p2p_transfer",
        is_new_payee=True,
        timestamp="2026-09-28T09:10:00+00:00",
    )
    assert posted.status_code == 200
    body = posted.json()
    if body["canonical_decision"] == "REVIEW":
        assert body["risk_tier"] in {"HOLD", "STEP_UP"}
        if body.get("action") == "STEP_UP":
            assert body["risk_tier"] == "STEP_UP"
