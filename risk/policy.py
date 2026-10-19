"""Action policy after the canonical ALLOW / REVIEW / BLOCK decision.

STEP_UP is not a rename of REVIEW. It is a follow-up action for mid-band
REVIEW plus a corroborating signal (velocity, amount shock, impossible travel,
or a first-time merchant/device on a larger send).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from risk.contracts import DecisionResult, RuleResult

# ₹. Small routine payments without serious rules are not queued.
ROUTINE_ALLOW_MAX_AMOUNT = 500.0
# First-time merchant/device OTP only at/above this amount.
STEP_UP_NEW_PARTY_MIN_AMOUNT = 2000.0
SERIOUS_RULES = frozenset(
    {
        "HIGH_VELOCITY",
        "AMOUNT_ANOMALY",
        "IMPOSSIBLE_TRAVEL",
        "FAILED_ATTEMPTS",
        "ATO_SUSPECTED",
        "HIGH_RISK_MERCHANT",
    }
)
NEW_PARTY_RULES = frozenset({"NEW_MERCHANT", "NEW_DEVICE"})


def _rule_names(result: Mapping[str, Any] | None = None, rules: RuleResult | None = None) -> set[str]:
    if rules is not None:
        return {item.rule for item in rules.triggered_rules}
    return {item.get("rule") for item in (result or {}).get("rules", {}).get("triggered_rules") or []}


def apply_routine_small_decision(
    decision: DecisionResult,
    rules: RuleResult,
    amount: float,
    ml_available: bool = True,
) -> DecisionResult:
    """Keep BLOCK. Soft REVIEW on a small send with no serious rule → ALLOW.

    Missing ML stays REVIEW — the conservative prior must not be washed into ALLOW.
    """
    if decision.decision != "REVIEW":
        return decision
    if not ml_available:
        return decision
    if float(amount) > ROUTINE_ALLOW_MAX_AMOUNT:
        return decision
    if _rule_names(rules=rules) & SERIOUS_RULES:
        return decision
    return replace(decision, decision="ALLOW")


def policy_action(result: Mapping[str, Any], amount: float | None = None) -> str:
    decision = str(result.get("decision") or "REVIEW")
    if decision == "ALLOW":
        return "ALLOW"
    if decision == "BLOCK":
        return "BLOCK"
    names = _rule_names(result=result)
    try:
        rupees = float(amount if amount is not None else result.get("amount") or 0)
    except (TypeError, ValueError):
        rupees = 0.0
    if names & SERIOUS_RULES:
        return "STEP_UP"
    if names & NEW_PARTY_RULES and rupees >= STEP_UP_NEW_PARTY_MIN_AMOUNT:
        return "STEP_UP"
    return "HOLD"
