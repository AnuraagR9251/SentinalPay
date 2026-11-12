"""Canonical score cuts. The blend weights are set so the rule score is the whole of R."""

from risk.aggregate import aggregate_and_decide
from risk.config import RiskConfig
from risk.contracts import BehaviorResult, MlResult, RuleResult, SecuritySignals
from risk.policy import policy_action

_CFG = RiskConfig(weight_rules=1.0, weight_behavior=0.0, weight_ml=0.0, weight_security=0.0)
_QUIET = SecuritySignals(False, False, False, False, 0)
_BEH = BehaviorResult(0, ())


def _decide(score: int, *, available: bool = True):
    return aggregate_and_decide(
        _QUIET,
        RuleResult(score, ()),
        _BEH,
        MlResult(0.0, "band", available=available),
        _CFG,
    )


def test_score_bands() -> None:
    assert _decide(0).decision == "ALLOW"
    assert _decide(29).decision == "ALLOW"
    assert _decide(30).decision == "REVIEW"
    assert _decide(69).decision == "REVIEW"
    assert _decide(70).decision == "BLOCK"
    assert _decide(100).decision == "BLOCK"
    assert _decide(0).risk_score == 0
    assert _decide(100).risk_score == 100


def test_missing_model_cannot_allow() -> None:
    out = _decide(0, available=False)
    assert out.risk_score == 0
    assert out.decision == "REVIEW"


def test_review_actions_stay_on_the_existing_policy() -> None:
    serious = policy_action(
        {"decision": "REVIEW", "amount": 100, "rules": {"triggered_rules": [{"rule": "HIGH_VELOCITY"}]}}
    )
    assert serious == "STEP_UP"
    new_party = policy_action(
        {"decision": "REVIEW", "amount": 48000, "rules": {"triggered_rules": [{"rule": "NEW_MERCHANT"}]}}
    )
    assert new_party == "STEP_UP"
    other = policy_action({"decision": "REVIEW", "amount": 100, "rules": {"triggered_rules": []}})
    assert other == "HOLD"
    small_new = policy_action(
        {"decision": "REVIEW", "amount": 200, "rules": {"triggered_rules": [{"rule": "NEW_DEVICE"}]}}
    )
    assert small_new == "HOLD"
