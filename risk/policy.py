"""Action shown to the payer, taken from the canonical 0–100 score.

    0–29   ALLOW
    30–50  STEP_UP
    51–69  HOLD
    70–100 BLOCK

Rules do not move a score into a different action. A missing model still
cannot produce ALLOW.
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
    del amount
    decision = str(result.get("decision") or "REVIEW")
    raw = result.get("risk_score")
    try:
        score = None if raw is None else int(raw)
    except (TypeError, ValueError):
        score = None
    if score is not None and score >= 70:
        return "BLOCK"
    if decision == "BLOCK":
        return "BLOCK"
    ml = result.get("ml") if isinstance(result.get("ml"), dict) else {}
    if score is None:
        return "ALLOW" if decision == "ALLOW" else "HOLD"
    if score <= 29:
        if ml.get("available") is False:
            return "HOLD"
        return "ALLOW"
    if score <= 50:
        return "STEP_UP"
    return "HOLD"
