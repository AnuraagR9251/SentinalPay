"""Layer checks for the evaluate pipeline."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from risk.aggregate import aggregate_and_decide
from risk.config import RiskConfig
from risk.contracts import BehaviorResult, MlResult, RuleResult, SecuritySignals, TriggeredRule
from risk.normalize import NormalizationError, normalize_transaction
from risk.pipeline import evaluate_transaction
from risk.store import RiskStore


def test_normalize_generates_id_and_inr() -> None:
    txn = normalize_transaction({"user_id": "USR_123", "amount": 8500, "merchant_id": "MERCHANT_456"})
    assert txn.transaction_id.startswith("TXN_")
    assert txn.currency == "INR"
    assert txn.merchant_id == "MERCHANT_456"


def test_normalize_rejects_bad_amount() -> None:
    try:
        normalize_transaction({"user_id": "USR_123", "amount": -1})
    except NormalizationError:
        return
    raise AssertionError("expected NormalizationError")


def test_decide_cutovers() -> None:
    cfg = RiskConfig()
    empty_rules = RuleResult(0, ())
    empty_beh = BehaviorResult(0, ())
    quiet = SecuritySignals(False, False, False, False, 0)
    allow = aggregate_and_decide(quiet, empty_rules, empty_beh, MlResult(0.02, "xgb_v1"), cfg)
    assert allow.decision == "ALLOW"
    hot_rules = RuleResult(80, (TriggeredRule("HIGH_VELOCITY", "HIGH", 80, "burst"),))
    block = aggregate_and_decide(quiet, hot_rules, BehaviorResult(80, ()), MlResult(0.9, "xgb_v1"), cfg)
    assert block.decision == "BLOCK"
    assert block.risk_factors


def test_pipeline_and_review(tmp_path: Path) -> None:
    store = RiskStore(tmp_path / "engine.db")
    now = datetime(2026, 9, 28, 10, 30, tzinfo=timezone.utc)
    first = evaluate_transaction(
        {
            "transaction_id": "TXN_10001",
            "user_id": "USR_123",
            "amount": 8500,
            "merchant_id": "MERCHANT_456",
            "merchant_category": "electronics",
            "timestamp": now.isoformat(),
            "device_id": "DEV_789",
            "ip_address": "192.168.1.10",
            "latitude": 12.9716,
            "longitude": 77.5946,
        },
        store=store,
        config=RiskConfig(),
    )
    assert first["transaction_id"] == "TXN_10001"
    assert first["decision"] in {"ALLOW", "REVIEW", "BLOCK"}
    assert "ml" in first and "rules" in first and "security" in first

    again = evaluate_transaction(
        {
            "transaction_id": "TXN_10001",
            "user_id": "USR_123",
            "amount": 8500,
            "merchant_id": "MERCHANT_456",
            "timestamp": now.isoformat(),
            "latitude": 12.9716,
            "longitude": 77.5946,
        },
        store=store,
        config=RiskConfig(),
    )
    assert again.get("idempotent") is True
    assert again["security"]["duplicate_transaction"] is True
    assert again["risk_score"] == first["risk_score"]
    assert again["decision"] == first["decision"]
    assert store.count_transactions("USR_123") == 1
    assert store.count_audits("TXN_10001") == 1
    names_first = {item["rule"] for item in first["rules"]["triggered_rules"]}
    assert "HIGH_RISK_MERCHANT" not in names_first
    assert first["location_baseline"] == "UNKNOWN"

    far = evaluate_transaction(
        {
            "transaction_id": "TXN_10002",
            "user_id": "USR_123",
            "amount": 8500,
            "merchant_id": "MERCHANT_456",
            "timestamp": (now + timedelta(minutes=8)).isoformat(),
            "device_id": "DEV_NEW",
            "latitude": 51.5074,
            "longitude": -0.1278,
            "recent_failures": 4,
        },
        store=store,
        config=RiskConfig(),
    )
    names = {item["rule"] for item in far["rules"]["triggered_rules"]}
    assert "IMPOSSIBLE_TRAVEL" in names or far["decision"] in {"REVIEW", "BLOCK"}

    if far["decision"] == "REVIEW":
        stored = store.submit_review(far["transaction_id"], "APPROVED", "known travel")
        assert stored["status"] == "APPROVED"
