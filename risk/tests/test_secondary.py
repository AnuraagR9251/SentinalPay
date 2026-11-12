"""Secondary HOLD policy. It does not rescore the fraud model."""

from datetime import datetime, timedelta, timezone

from risk.secondary import assess_secondary, same_binding


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
    assert decision["outcome"] == "APPROVE"
    assert "fraud_probability" not in decision


def test_serious_primary_rule_rejects() -> None:
    decision = assess_secondary(_evidence(triggered_rules=["HIGH_VELOCITY"]))
    assert decision["outcome"] == "REJECT"
    assert "serious_primary_rule" in decision["reasons"]


def test_amount_far_above_history_rejects() -> None:
    decision = assess_secondary(_evidence(amount=100))
    assert decision["outcome"] == "REJECT"
    assert "amount_deviation" in decision["reasons"]


def test_missing_history_holds() -> None:
    decision = assess_secondary(_evidence(history=[]))
    assert decision["outcome"] == "CONTINUE_HOLD"
    assert "missing_history" in decision["reasons"]


def test_unavailable_model_holds() -> None:
    hidden = _evidence(model_available=False)
    decision = assess_secondary(hidden)
    assert decision["outcome"] == "CONTINUE_HOLD"
    assert decision["reasons"] == ["model_unavailable"]


def test_missing_failure_signal_is_not_treated_as_clean() -> None:
    evidence = _evidence()
    evidence["recent_failures"] = None
    evidence["failed_payments"] = None
    decision = assess_secondary(evidence)
    assert decision["outcome"] == "CONTINUE_HOLD"
    assert "failures_unavailable" in decision["reasons"]


def test_new_payee_holds_instead_of_approving() -> None:
    decision = assess_secondary(_evidence(merchant_id="other@upi"))
    assert decision["outcome"] == "CONTINUE_HOLD"
    assert "new_payee" in decision["reasons"]


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
    assert decision["outcome"] == "REJECT"
    assert "location_inconsistent" in decision["reasons"]


def test_binding_rejects_a_changed_device() -> None:
    stored = {"user_id": "a", "amount_paise": 100, "currency": "INR", "merchant_id": "shop@upi", "device_id": "dev-1", "latitude": 12.97, "longitude": 77.59}
    changed = dict(stored)
    changed["device_id"] = "dev-2"
    assert same_binding(stored, stored)
    assert same_binding(stored, changed) is False
