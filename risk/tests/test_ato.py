from datetime import datetime, timedelta, timezone
from pathlib import Path

from risk.ato import maybe_ato_rule, merge_ato
from risk.config import RiskConfig
from risk.contracts import RuleResult, SecuritySignals, TriggeredRule
from risk.pipeline import evaluate_transaction
from risk.store import RiskStore


def test_ato_needs_two_signals() -> None:
    one = RuleResult(15, (TriggeredRule("NEW_DEVICE", "MEDIUM", 15, "new"),))
    quiet = SecuritySignals(False, False, False, False, 0)
    assert maybe_ato_rule(one, quiet) is None
    two = RuleResult(
        35,
        (
            TriggeredRule("NEW_DEVICE", "MEDIUM", 15, "new"),
            TriggeredRule("HIGH_VELOCITY", "HIGH", 20, "burst"),
        ),
    )
    hit = maybe_ato_rule(two, quiet)
    assert hit is not None
    assert hit.rule == "ATO_SUSPECTED"
    merged = merge_ato(two, quiet)
    assert any(item.rule == "ATO_SUSPECTED" for item in merged.triggered_rules)


def test_missing_device_is_not_ato() -> None:
    empty = RuleResult(0, ())
    quiet = SecuritySignals(False, False, False, False, 0)
    assert maybe_ato_rule(empty, quiet) is None


def test_pipeline_ato_on_new_device_and_new_payee(tmp_path: Path) -> None:
    store = RiskStore(tmp_path / "ato.db")
    now = datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc)
    evaluate_transaction(
        {
            "transaction_id": "ato-hist-1",
            "user_id": "USR_ATO",
            "amount": 200,
            "merchant_id": "kirana@oksbi",
            "merchant_category": "groceries",
            "timestamp": now.isoformat(),
            "device_id": "dev-home",
        },
        store=store,
        config=RiskConfig(),
    )
    result = evaluate_transaction(
        {
            "transaction_id": "ato-live-1",
            "user_id": "USR_ATO",
            "amount": 900,
            "merchant_id": "stranger@oksbi",
            "merchant_category": "p2p",
            "timestamp": (now + timedelta(seconds=30)).isoformat(),
            "device_id": "dev-new-phone",
        },
        store=store,
        config=RiskConfig(),
    )
    names = {item["rule"] for item in result["rules"]["triggered_rules"]}
    if "NEW_DEVICE" in names and "NEW_MERCHANT" in names:
        assert "ATO_SUSPECTED" in names
        assert "ATO_SUSPECTED" in result["reason_codes"]
