"""Same transaction_id is claimed once at persist, even under threads."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import pytest

from risk.config import RiskConfig
from risk.pipeline import ConflictError, evaluate_transaction
from risk.store import RiskStore, payment_identity


def _payload(**overrides: object) -> dict:
    body = {
        "transaction_id": "TXN_IDEM_1",
        "user_id": "USR_IDEM",
        "amount": 900,
        "currency": "INR",
        "merchant_id": "shop@oksbi",
        "merchant_category": "dining",
        "timestamp": datetime(2026, 9, 28, 11, 0, tzinfo=timezone.utc).isoformat(),
        "latitude": 12.9716,
        "longitude": 77.5946,
        "device_id": "dev-idem",
    }
    body.update(overrides)
    return body


def test_payment_identity_is_deterministic() -> None:
    assert payment_identity("u", 900, "inr", "m") == payment_identity("u", 900.0, "INR", "m")
    assert payment_identity("u", 900, "INR", "m") != payment_identity("u", 901, "INR", "m")
    assert payment_identity("a", 900, "INR", "m") != payment_identity("b", 900, "INR", "m")


def test_identical_retry_returns_cached_without_new_audit(tmp_path: Path) -> None:
    store = RiskStore(tmp_path / "idem.db", seed_demo=False)
    first = evaluate_transaction(_payload(), store=store, config=RiskConfig())
    second = evaluate_transaction(_payload(), store=store, config=RiskConfig())
    assert second.get("idempotent") is True
    assert second["risk_score"] == first["risk_score"]
    assert second["decision"] == first["decision"]
    assert second["user_id"] == first["user_id"]
    assert store.count_transactions("USR_IDEM") == 1
    assert store.count_audits("TXN_IDEM_1") == 1


def test_same_id_changed_amount_is_conflict(tmp_path: Path) -> None:
    store = RiskStore(tmp_path / "amt.db", seed_demo=False)
    first = evaluate_transaction(_payload(), store=store, config=RiskConfig())
    with pytest.raises(ConflictError, match="different payment details"):
        evaluate_transaction(_payload(amount=1200), store=store, config=RiskConfig())
    assert store.get_result("TXN_IDEM_1")["risk_score"] == first["risk_score"]
    assert store.count_audits("TXN_IDEM_1") == 1


def test_same_id_changed_user_is_conflict(tmp_path: Path) -> None:
    store = RiskStore(tmp_path / "user.db", seed_demo=False)
    first = evaluate_transaction(_payload(), store=store, config=RiskConfig())
    with pytest.raises(ConflictError, match="different payment details") as caught:
        evaluate_transaction(_payload(user_id="USR_OTHER"), store=store, config=RiskConfig())
    assert "USR_IDEM" not in str(caught.value)
    assert store.get_transaction("TXN_IDEM_1")["user_id"] == "USR_IDEM"
    assert store.get_result("TXN_IDEM_1")["user_id"] == first["user_id"]
    assert store.count_transactions("USR_OTHER") == 0


def test_concurrent_same_id_writes_one_audit(tmp_path: Path) -> None:
    store = RiskStore(tmp_path / "conc.db")
    payload = _payload(transaction_id="TXN_RACE_1", user_id="USR_RACE")

    def _run() -> dict:
        return evaluate_transaction(payload, store=store, config=RiskConfig())

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(_run) for _ in range(8)]
        results = [fut.result() for fut in as_completed(futs)]

    scores = {item["risk_score"] for item in results}
    decisions = {item["decision"] for item in results}
    assert len(scores) == 1
    assert len(decisions) == 1
    assert store.count_transactions("USR_RACE") == 1
    assert store.count_audits("TXN_RACE_1") == 1


def test_concurrent_conflicting_payloads_one_wins(tmp_path: Path) -> None:
    store = RiskStore(tmp_path / "cf.db", seed_demo=False)

    def _run(user_id: str, amount: float) -> tuple[str, object]:
        try:
            result = evaluate_transaction(
                _payload(transaction_id="TXN_CF_1", user_id=user_id, amount=amount),
                store=store,
                config=RiskConfig(),
            )
            return ("ok", result)
        except ConflictError as exc:
            return ("conflict", str(exc))

    with ThreadPoolExecutor(max_workers=2) as pool:
        futs = [
            pool.submit(_run, "USR_A", 900),
            pool.submit(_run, "USR_B", 999),
        ]
        outcomes = [fut.result() for fut in as_completed(futs)]

    oks = [item for item in outcomes if item[0] == "ok"]
    conflicts = [item for item in outcomes if item[0] == "conflict"]
    assert len(oks) == 1
    assert len(conflicts) == 1
    assert "risk_score" not in str(conflicts[0][1])
    winner = oks[0][1]["user_id"]
    stored = store.get_transaction("TXN_CF_1")
    assert stored is not None
    assert stored["user_id"] == winner
    assert store.count_audits("TXN_CF_1") == 1
