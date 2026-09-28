"""Combine layer scores, explain them, and map to ALLOW / REVIEW / BLOCK."""

from __future__ import annotations

from risk.config import RiskConfig
from risk.contracts import (
    BehaviorResult,
    DecisionResult,
    MlResult,
    RiskFactor,
    RuleResult,
    SecuritySignals,
)


def _impact(score: float) -> str:
    if score >= 20:
        return "HIGH"
    if score >= 10:
        return "MEDIUM"
    return "LOW"


def aggregate_and_decide(
    security: SecuritySignals,
    rules: RuleResult,
    behavior: BehaviorResult,
    ml: MlResult,
    config: RiskConfig,
) -> DecisionResult:
    components = {
        "rules": rules.rule_score * config.weight_rules,
        "behavior": behavior.behavioral_score * config.weight_behavior,
        "ml": ml.fraud_probability * 100.0 * config.weight_ml,
        "security": security.security_risk_score * config.weight_security,
    }
    risk_score = int(round(min(100.0, max(0.0, sum(components.values())))))

    factors: list[RiskFactor] = []
    for item in rules.triggered_rules:
        factors.append(RiskFactor(factor=item.reason, impact=item.severity))
    for item in behavior.anomalies:
        factors.append(RiskFactor(factor=f"Behavioral deviation: {item.feature}", impact=item.severity))
    for note in security.notes:
        factors.append(RiskFactor(factor=note, impact=_impact(15)))
    if ml.fraud_probability >= 0.6:
        factors.append(
            RiskFactor(factor="Model assigned a high fraud probability", impact="HIGH")
        )
    # Keep the public list short — no raw feature dump / SHAP values.
    factors = factors[:8]

    if risk_score <= config.allow_max:
        decision = "ALLOW"
        confidence = max(0.5, 1.0 - risk_score / 100.0)
    elif risk_score <= config.review_max:
        decision = "REVIEW"
        confidence = max(0.5, 1.0 - abs(risk_score - 50) / 50.0)
    else:
        decision = "BLOCK"
        confidence = max(0.55, risk_score / 100.0)

    return DecisionResult(
        risk_score=risk_score,
        decision=decision,
        confidence=round(min(0.99, confidence), 2),
        risk_factors=tuple(factors),
        components=components,
    )
