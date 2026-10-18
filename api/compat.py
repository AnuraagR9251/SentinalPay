"""Legacy /score adapter. Translation only — no independent scoring.

Canonical engine: ALLOW / REVIEW / BLOCK on a 0–100 score.
Frontend contract: ALLOW / STEP_UP / HOLD / BLOCK on a 0–1 score.

Phase 1 mapping (STEP_UP is not invented from REVIEW):

    ALLOW  → ALLOW
    REVIEW → HOLD
    BLOCK  → BLOCK
"""

from __future__ import annotations

from typing import Any, Mapping

from risk.policy import policy_action

# Compatibility only. REVIEW is a human queue, not an OTP step-up.
_CANONICAL_TO_LEGACY = {
    "ALLOW": "ALLOW",
    "REVIEW": "HOLD",
    "BLOCK": "BLOCK",
}


def pipeline_payload_from_score(raw: Mapping[str, Any]) -> dict[str, Any]:
    loc = raw.get("payer_location") or {}
    return {
        "transaction_id": raw.get("transaction_id"),
        "user_id": raw.get("user_id"),
        "amount": raw.get("amount"),
        "currency": "INR",
        "merchant_id": raw.get("payee_vpa"),
        "merchant_category": raw.get("purpose"),
        "timestamp": raw.get("timestamp"),
        "latitude": loc.get("lat"),
        "longitude": loc.get("lon"),
        "device_id": raw.get("device_id"),
    }


def legacy_fields_from_canonical(result: Mapping[str, Any]) -> dict[str, Any]:
    decision = str(result.get("decision") or "REVIEW")
    action = str(result.get("action") or policy_action(result))
    if action == "STEP_UP":
        tier = "STEP_UP"
    else:
        tier = _CANONICAL_TO_LEGACY.get(decision, "HOLD")
    score_100 = int(result.get("risk_score") or 0)
    p_ml = float((result.get("ml") or {}).get("fraud_probability") or result.get("fraud_probability") or 0.0)
    hits = [
        {"name": item.get("rule") or item.get("factor") or "signal", "value": float(item.get("score") or 0) / 100.0}
        for item in (result.get("rules") or {}).get("triggered_rules") or []
    ]
    if not hits:
        hits = [
            {"name": item.get("factor") or "factor", "value": 1.0 if item.get("impact") == "HIGH" else 0.5}
            for item in result.get("risk_factors") or []
        ]
    return {
        "transaction_id": result["transaction_id"],
        "risk_score": score_100 / 100.0,
        "risk_tier": tier,
        "canonical_decision": decision,
        "canonical_risk_score": score_100,
        "action": action,
        "P_xgb": p_ml,
        "P_ae": None,
        "P_graph": None,
        "P_hybrid": score_100 / 100.0,
        "structuring_flag": None,
        "ae_available": False,
        "graph_available": False,
        "structuring_available": False,
        "ml_available": bool((result.get("ml") or {}).get("available"))
        if isinstance(result.get("ml"), dict)
        else None,
        "top_contributing_features": hits[:5],
        "contributions": hits,
        "action_required": tier != "ALLOW",
    }
