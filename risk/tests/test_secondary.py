"""Secondary HOLD policy. It does not rescore the fraud model."""

from datetime import datetime, timedelta, timezone

from pathlib import Path

from risk.secondary import ASSESSMENT_DEADLINE_S, advance_assessment, assess_secondary, resolve_hold, same_binding
from risk.store import RiskStore


def _evidence(**overrides):
    now = datetime.now(timezone.utc)
    history = []
    for i in range(5):
        history.append(
            {
                "transaction_id": f"h{i}",
                "amount": 10,
                "merchant_id": "shop@upi",
                "device_id": "dev-1",
                "timestamp": (now - timedelta(days=i + 1)).isoformat(),
                "latitude": 12.97,
                "longitude": 77.59,
            }
        )
    evidence = {
        "amount": 10.0,
        "history": history,
        "device_id": "dev-1",
        "merchant_id": "shop@upi",
        "latitude": 12.97,
        "longitude": 77.59,
        "timestamp": now.isoformat(),
        "triggered_rules": [],
        "model_available": True,
        "recent_failures": 0,
        "failed_payments": 0,
    }
    evidence.update(overrides)
    return evidence


def test_consistent_history_approves_without_a_model_score() -> None:
    decision = assess_secondary(_evidence())
    assert decision["outcome"] == "ALLOW"
    assert "fraud_probability" not in decision


def test_serious_primary_rule_rejects() -> None:
    decision = assess_secondary(_evidence(triggered_rules=["HIGH_VELOCITY"]))
    assert decision["outcome"] == "DECLINE"
    assert "serious_primary_rule" in decision["reasons"]


def test_amount_far_above_history_rejects() -> None:
    decision = assess_secondary(_evidence(amount=100))
    assert decision["outcome"] == "DECLINE"
    assert "amount_deviation" in decision["reasons"]


def test_missing_history_is_not_an_approval() -> None:
    decision = assess_secondary(_evidence(history=[]))
    assert decision["outcome"] == "PENDING"
    assert "missing_history" in decision["reasons"]


def test_unavailable_model_holds() -> None:
    hidden = _evidence(model_available=False)
    decision = assess_secondary(hidden)
    assert decision["outcome"] == "PENDING"
    assert decision["reasons"] == ["model_unavailable"]


def test_missing_failure_signal_is_not_treated_as_clean() -> None:
    evidence = _evidence()
    evidence["recent_failures"] = None
    evidence["failed_payments"] = None
    decision = assess_secondary(evidence)
    assert decision["outcome"] == "PENDING"
    assert "failures_unavailable" in decision["reasons"]


def test_no_checkout_history_is_not_treated_as_unknown() -> None:
    decision = assess_secondary(_evidence(failed_payments={"state": "no_history", "count": 0}))
    assert decision["outcome"] == "ALLOW"
    assert "checkout_no_history" in decision["reasons"]
    assert "failures_unavailable" not in decision["reasons"]


def test_new_payee_on_a_known_device_can_allow() -> None:
    decision = assess_secondary(_evidence(merchant_id="other@upi"))
    assert decision["outcome"] == "ALLOW"
    assert "new_payee_allowed" in decision["reasons"]


def test_new_device_to_a_known_payee_can_allow() -> None:
    decision = assess_secondary(_evidence(device_id="dev-2"))
    assert decision["outcome"] == "ALLOW"
    assert "new_device_allowed" in decision["reasons"]


def test_new_device_and_new_payee_stay_pending() -> None:
    decision = assess_secondary(_evidence(device_id="dev-2", merchant_id="other@upi"))
    assert decision["outcome"] == "PENDING"
    assert "unfamiliar_party" in decision["reasons"]


def test_strong_graph_declines_without_changing_a_score() -> None:
    decision = assess_secondary(_evidence(graph_state="strong"))
    assert decision["outcome"] == "DECLINE"
    assert "graph_network" in decision["reasons"]
    assert "fraud_probability" not in decision


def test_strong_autoencoder_does_not_decline_consistent_history() -> None:
    decision = assess_secondary(_evidence(ae_state="strong"))
    assert decision["outcome"] == "ALLOW"
    assert "ae_anomaly" in decision["reasons"]


def test_impossible_location_rejects() -> None:
    evidence = _evidence()
    now = datetime.now(timezone.utc)
    evidence["history"][-1]["timestamp"] = (now - timedelta(minutes=1)).isoformat()
    evidence["history"][-1]["latitude"] = 28.61
    evidence["history"][-1]["longitude"] = 77.21
    evidence["latitude"] = 19.07
    evidence["longitude"] = 72.87
    evidence["timestamp"] = now.isoformat()
    decision = assess_secondary(evidence)
    assert decision["outcome"] == "DECLINE"
    assert "location_inconsistent" in decision["reasons"]


def _row(store: RiskStore, outcome: str, transaction_id: str = "tx-clock") -> None:
    store.put_secondary_assessment(
        {
            "transaction_id": transaction_id,
            "user_id": "a",
            "amount_paise": 100,
            "currency": "INR",
            "merchant_id": "shop@upi",
            "device_id": "dev-1",
            "latitude": 12.97,
            "longitude": 77.59,
            "outcome": outcome,
            "reasons": ["history_consistent"],
            "primary_action": "HOLD",
            "primary_decision": "REVIEW",
            "primary_score": 44,
            "ttl_s": ASSESSMENT_DEADLINE_S,
        }
    )


def test_deadline_declines_pending_and_expires_allow(tmp_path: Path) -> None:
    store = RiskStore(tmp_path / "clock.db")
    _row(store, "PENDING", "tx-pending")
    _row(store, "ALLOW", "tx-allow")
    later = datetime.now(timezone.utc) + timedelta(seconds=ASSESSMENT_DEADLINE_S + 1)
    pending = advance_assessment(store, "tx-pending", now=later)
    still_open = advance_assessment(store, "tx-allow", now=later)
    assert pending["outcome"] == "DECLINE"
    assert "deadline_expired" in pending["reasons"]
    assert still_open["outcome"] == "ALLOW"
    allowed = advance_assessment(
        store,
        "tx-allow",
        now=later + timedelta(seconds=60),
    )
    assert allowed["outcome"] == "EXPIRED"
    assert "approval_expired" in allowed["reasons"]
    again = advance_assessment(store, "tx-pending", now=later)
    assert again["outcome"] == "DECLINE"


def test_repeated_resolution_keeps_the_terminal_result(tmp_path: Path) -> None:
    store = RiskStore(tmp_path / "replay.db")
    fields = {
        "transaction_id": "tx-once",
        "user_id": "a",
        "amount_paise": 1000,
        "currency": "INR",
        "merchant_id": "shop@upi",
        "device_id": "dev-1",
        "latitude": 12.97,
        "longitude": 77.59,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    result = {
        "transaction_id": "tx-once",
        "action": "HOLD",
        "decision": "REVIEW",
        "risk_score": 44,
        "rules": {"triggered_rules": []},
        "ml": {"available": True},
        "recent_failures": 0,
    }
    calls = {"n": 0}
    real = assess_secondary

    def wrapped(evidence):
        calls["n"] += 1
        return real(evidence)

    import risk.secondary as secondary

    previous = secondary.assess_secondary
    secondary.assess_secondary = wrapped
    try:
        first = resolve_hold(store, result, fields)
        second = resolve_hold(store, result, fields)
    finally:
        secondary.assess_secondary = previous
    assert first["outcome"] == second["outcome"]
    assert calls["n"] == 1


def test_changed_binding_is_not_reused(tmp_path: Path) -> None:
    store = RiskStore(tmp_path / "bind.db")
    fields = {
        "transaction_id": "tx-bind",
        "user_id": "a",
        "amount_paise": 1000,
        "currency": "INR",
        "merchant_id": "shop@upi",
        "device_id": "dev-1",
        "latitude": 12.97,
        "longitude": 77.59,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    result = {
        "transaction_id": "tx-bind",
        "action": "HOLD",
        "decision": "REVIEW",
        "risk_score": 44,
        "rules": {"triggered_rules": []},
        "ml": {"available": False},
        "recent_failures": 0,
    }
    resolve_hold(store, result, fields)
    changed = dict(fields)
    changed["merchant_id"] = "other@upi"
    conflict = resolve_hold(store, result, changed)
    assert conflict["conflict"] is True
    assert store.get_secondary_assessment("tx-bind")["merchant_id"] == "shop@upi"


def test_binding_rejects_a_changed_device() -> None:
    stored = {"user_id": "a", "amount_paise": 100, "currency": "INR", "merchant_id": "shop@upi", "device_id": "dev-1", "latitude": 12.97, "longitude": 77.59}
    changed = dict(stored)
    changed["device_id"] = "dev-2"
    assert same_binding(stored, stored)
    assert same_binding(stored, changed) is False
