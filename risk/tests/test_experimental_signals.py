"""AE/graph are reported experimentally and do not drive ALLOW/REVIEW/BLOCK."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from detection.autoencoder_scorer import AeResult
from risk.config import RiskConfig
from risk.pipeline import evaluate_transaction
from risk.store import RiskStore

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)


def _payload(**overrides):
    body = {
        "transaction_id": "exp-1",
        "user_id": "USR_EXP",
        "amount": 240.0,
        "merchant_id": "kirana.exp@oksbi",
        "merchant_category": "groceries",
        "timestamp": NOW.isoformat(),
        "device_id": "dev-exp-1",
        "latitude": 12.9716,
        "longitude": 77.5946,
    }
    body.update(overrides)
    return body


def test_empty_history_graph_available_zero(tmp_path: Path) -> None:
    store = RiskStore(tmp_path / "empty.db")
    result = evaluate_transaction(_payload(), store=store, config=RiskConfig())
    exp = result["experimental"]
    assert exp["graph_available"] is True
    assert exp["fan_out_count"] == 1
    assert exp["P_graph"] == pytest.approx(0.15 / 8.0)
    assert exp["structuring_flag"] is False
    if exp["ae_available"]:
        assert exp["P_ae"] is not None
        assert 0.0 <= exp["P_ae"] <= 1.0
    else:
        assert exp["P_ae"] is None


def test_fan_out_graph_score_increases(tmp_path: Path) -> None:
    store = RiskStore(tmp_path / "fan.db")
    cfg = RiskConfig()
    user = "USR_FAN"
    for i in range(6):
        evaluate_transaction(
            _payload(
                transaction_id=f"fan-{i}",
                user_id=user,
                merchant_id=f"shop{i}@oksbi",
                timestamp=(NOW + timedelta(minutes=i)).isoformat(),
            ),
            store=store,
            config=cfg,
        )
    last = evaluate_transaction(
        _payload(
            transaction_id="fan-last",
            user_id=user,
            merchant_id="shop-last@oksbi",
            timestamp=(NOW + timedelta(minutes=20)).isoformat(),
        ),
        store=store,
        config=cfg,
    )
    assert last["experimental"]["graph_available"] is True
    assert last["experimental"]["fan_out_count"] >= 6
    assert last["experimental"]["P_graph"] > 0.0


def test_structuring_flag_from_window(tmp_path: Path) -> None:
    store = RiskStore(tmp_path / "struct.db")
    cfg = RiskConfig()
    user = "USR_SMURF"
    for i, amount in enumerate((18000.0, 19000.0, 17000.0)):
        evaluate_transaction(
            _payload(
                transaction_id=f"smurf-{i}",
                user_id=user,
                amount=amount,
                merchant_id="mule.cash@okaxis",
                timestamp=(NOW + timedelta(minutes=i * 4)).isoformat(),
            ),
            store=store,
            config=cfg,
        )
    flagged = evaluate_transaction(
        _payload(
            transaction_id="smurf-4",
            user_id=user,
            amount=16000.0,
            merchant_id="mule.cash@okaxis",
            timestamp=(NOW + timedelta(minutes=20)).isoformat(),
        ),
        store=store,
        config=cfg,
    )
    assert flagged["experimental"]["structuring_flag"] is True
    assert flagged["experimental"]["P_graph"] >= 0.40


def test_mule_chain_from_store_history(tmp_path: Path) -> None:
    store = RiskStore(tmp_path / "mule.db")
    cfg = RiskConfig()
    chain = [f"USR_MULE_{i}" for i in range(6)]
    for i in range(len(chain) - 1):
        evaluate_transaction(
            _payload(
                transaction_id=f"mule-{i}",
                user_id=chain[i],
                merchant_id=chain[i + 1],
                amount=8000.0,
                timestamp=(NOW + timedelta(minutes=i * 3)).isoformat(),
            ),
            store=store,
            config=cfg,
        )
    last = evaluate_transaction(
        _payload(
            transaction_id="mule-last",
            user_id=chain[0],
            merchant_id=chain[1],
            amount=8000.0,
            timestamp=(NOW + timedelta(minutes=30)).isoformat(),
        ),
        store=store,
        config=cfg,
    )
    assert last["experimental"]["mule_cluster"] is True
    assert last["experimental"]["cluster_size"] >= 5
    assert last["experimental"]["P_graph"] >= 0.35


def test_old_edges_do_not_form_mule_cluster(tmp_path: Path) -> None:
    store = RiskStore(tmp_path / "old.db")
    cfg = RiskConfig()
    stale = NOW - timedelta(days=3)
    chain = [f"USR_OLD_{i}" for i in range(6)]
    for i in range(len(chain) - 1):
        evaluate_transaction(
            _payload(
                transaction_id=f"old-{i}",
                user_id=chain[i],
                merchant_id=chain[i + 1],
                amount=8000.0,
                timestamp=(stale + timedelta(minutes=i)).isoformat(),
            ),
            store=store,
            config=cfg,
        )
    now_hit = evaluate_transaction(
        _payload(
            transaction_id="old-now",
            user_id=chain[0],
            merchant_id="fresh@oksbi",
            timestamp=NOW.isoformat(),
        ),
        store=store,
        config=cfg,
    )
    assert now_hit["experimental"]["mule_cluster"] is False


def test_duplicate_id_does_not_double_count(tmp_path: Path) -> None:
    store = RiskStore(tmp_path / "dup.db")
    cfg = RiskConfig()
    first = evaluate_transaction(_payload(transaction_id="dup-exp"), store=store, config=cfg)
    second = evaluate_transaction(_payload(transaction_id="dup-exp"), store=store, config=cfg)
    assert second.get("idempotent") is True
    assert first["experimental"]["P_graph"] == second["experimental"]["P_graph"]
    assert store.windowed_transactions(NOW, 86400 * 2)
    ids = [row["transaction_id"] for row in store.windowed_transactions(NOW, 86400 * 2)]
    assert ids.count("dup-exp") == 1


def test_high_experimental_scores_do_not_change_decision(tmp_path: Path, monkeypatch) -> None:
    payload = _payload(transaction_id="blend-a", user_id="USR_BLEND")
    first = evaluate_transaction(payload, store=RiskStore(tmp_path / "a.db"), config=RiskConfig())
    monkeypatch.setattr(
        "risk.pipeline.infer_autoencoder",
        lambda _vector: AeResult(available=True, score=1.0, error=None, threshold=0.1, n_features=10),
    )
    monkeypatch.setattr("risk.pipeline.score_graph", lambda *args, **kwargs: 1.0)
    second = evaluate_transaction(
        {**payload, "transaction_id": "blend-b"},
        store=RiskStore(tmp_path / "b.db"),
        config=RiskConfig(),
    )
    assert first["decision"] == second["decision"]
    assert first["risk_score"] == second["risk_score"]
    assert second["experimental"]["P_graph"] == 1.0
    assert second["experimental"]["P_ae"] == 1.0
