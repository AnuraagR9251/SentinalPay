from dataclasses import replace

from risk.contracts import DecisionResult, RuleResult, TriggeredRule
from risk.policy import apply_routine_small_decision, policy_action

_REVIEW = DecisionResult(risk_score=40, decision="REVIEW", confidence=0.5, risk_factors=())


def test_review_plus_new_merchant_is_step_up() -> None:
    action = policy_action(
        {
            "decision": "REVIEW",
            "amount": 48000,
            "rules": {"triggered_rules": [{"rule": "NEW_MERCHANT"}]},
        }
    )
    assert action == "STEP_UP"


def test_small_new_party_review_is_hold_not_step_up() -> None:
    assert (
        policy_action(
            {
                "decision": "REVIEW",
                "amount": 200,
                "rules": {"triggered_rules": [{"rule": "NEW_DEVICE"}]},
            }
        )
        == "HOLD"
    )


def test_small_velocity_review_is_step_up() -> None:
    assert (
        policy_action(
            {
                "decision": "REVIEW",
                "amount": 200,
                "rules": {"triggered_rules": [{"rule": "HIGH_VELOCITY"}]},
            }
        )
        == "STEP_UP"
    )


def test_review_without_new_party_is_hold() -> None:
    assert policy_action({"decision": "REVIEW", "rules": {"triggered_rules": []}}) == "HOLD"


def test_allow_and_block_stay_canonical() -> None:
    assert policy_action({"decision": "ALLOW"}) == "ALLOW"
    assert policy_action({"decision": "BLOCK"}) == "BLOCK"


def test_routine_small_review_without_serious_rule_becomes_allow() -> None:
    rules = RuleResult(15, (TriggeredRule("NEW_DEVICE", "MEDIUM", 15, "new"),))
    out = apply_routine_small_decision(_REVIEW, rules, 200)
    assert out.decision == "ALLOW"


def test_routine_small_keeps_review_when_velocity_hits() -> None:
    rules = RuleResult(20, (TriggeredRule("HIGH_VELOCITY", "HIGH", 20, "burst"),))
    out = apply_routine_small_decision(_REVIEW, rules, 200)
    assert out.decision == "REVIEW"


def test_routine_small_does_not_unblock() -> None:
    blocked = replace(_REVIEW, decision="BLOCK")
    rules = RuleResult(15, (TriggeredRule("NEW_DEVICE", "MEDIUM", 15, "new"),))
    assert apply_routine_small_decision(blocked, rules, 200).decision == "BLOCK"


def test_routine_small_keeps_review_when_ml_unavailable() -> None:
    rules = RuleResult(15, (TriggeredRule("NEW_DEVICE", "MEDIUM", 15, "new"),))
    out = apply_routine_small_decision(_REVIEW, rules, 200, ml_available=False)
    assert out.decision == "REVIEW"
