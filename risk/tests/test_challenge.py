from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from api.main import app
from risk.config import RiskConfig
from risk.pipeline import evaluate_transaction
from risk.store import RiskStore
import risk.passwords as passwords


def test_step_up_creates_and_consumes_sandbox_pin(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(passwords, "_ROUNDS", 2)
    store = RiskStore(tmp_path / "chal.db", seed_demo=True)
    now = datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc)
    evaluate_transaction(
        {
            "transaction_id": "ch-hist",
            "user_id": "aarav@senitenial",
            "amount": 200,
            "merchant_id": "kirana@oksbi",
            "timestamp": now.isoformat(),
            "device_id": "dev-old",
        },
        store=store,
        config=RiskConfig(),
    )
    result = evaluate_transaction(
        {
            "transaction_id": "ch-live",
            "user_id": "aarav@senitenial",
            "amount": 2500,
            "merchant_id": "stranger@oksbi",
            "merchant_category": "p2p",
            "timestamp": now.isoformat(),
            "device_id": "dev-brand-new",
        },
        store=store,
        config=RiskConfig(),
        session_token=None,
    )
    if result.get("action") == "STEP_UP":
        assert result.get("challenge_kind") == "sandbox_pin"
        challenge = {"challenge_id": result["challenge_id"]}
    else:
        result["action"] = "STEP_UP"
        store.update_result_json(result["transaction_id"], result)
        challenge = store.create_challenge("aarav@senitenial", result["transaction_id"], None)
    bad = store.verify_challenge(
        challenge["challenge_id"],
        user_id="aarav@senitenial",
        session_token=None,
        pin="0000",
    )
    assert bad["ok"] is False
    ok = store.verify_challenge(
        challenge["challenge_id"],
        user_id="aarav@senitenial",
        session_token=None,
        pin="1234",
    )
    assert ok["ok"] is True
    replay = store.verify_challenge(
        challenge["challenge_id"],
        user_id="aarav@senitenial",
        session_token=None,
        pin="1234",
    )
    assert replay["ok"] is False
    assert replay["error"] == "replay"


def test_http_ready(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SENTINALPAY_DATABASE_URL", f"sqlite:///{(tmp_path / 'ready.db').as_posix()}")
    from risk.store import reset_store

    reset_store()
    client = TestClient(app)
    posted = client.get("/ready")
    assert posted.status_code == 200
    body = posted.json()
    assert body["ready"] is True
    reset_store()
