"""Combine layer scores, then apply a configurable policy.

`fraud_probability` is the model P(fraud) in [0, 1].
`risk_score` is a 0–100 blend of rules, behavior, ML, and security.
ALLOW / REVIEW / BLOCK is cut from `risk_score` using config thresholds
(demo starting values, not calibrated operating points).
"""

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
    if not ml.available:
        factors.insert(
            0,
            RiskFactor(
                factor="ML model unavailable — conservative prior 0.5; ALLOW disabled",
                impact="HIGH",
            ),
        )
    elif ml.fraud_probability >= 0.6:
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

    if not ml.available and decision == "ALLOW":
        decision = "REVIEW"
        confidence = min(confidence, 0.55)

    return DecisionResult(
        risk_score=risk_score,
        decision=decision,
        confidence=round(min(0.99, confidence), 2),
        risk_factors=tuple(factors),
        components=components,
        fraud_probability=float(ml.fraud_probability),
        policy={
            "allow_max": config.allow_max,
            "review_max": config.review_max,
            "note": "demo starting cutovers on blended risk_score; fraud_probability is separate",
        },
    )
