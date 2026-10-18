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
    ml = result.get("ml") if isinstance(result.get("ml"), dict) else None
    if ml is None:
        ml_available = None
    elif "available" not in ml:
        ml_available = None
    else:
        ml_available = bool(ml["available"])
    if ml_available is True:
        raw_p = ml.get("fraud_probability")
        if raw_p is None:
            raw_p = result.get("fraud_probability")
        p_ml = None if raw_p is None else float(raw_p)
    else:
        p_ml = None
    hits = [
        {"name": item.get("rule") or item.get("factor") or "signal", "value": float(item.get("score") or 0) / 100.0}
        for item in (result.get("rules") or {}).get("triggered_rules") or []
    ]
    if not hits:
        hits = [
            {"name": item.get("factor") or "factor", "value": 1.0 if item.get("impact") == "HIGH" else 0.5}
            for item in result.get("risk_factors") or []
        ]
    exp = result.get("experimental") if isinstance(result.get("experimental"), dict) else {}
    ae_available = bool(exp.get("ae_available"))
    graph_available = bool(exp.get("graph_available"))
    p_ae = exp.get("P_ae") if ae_available else None
    p_graph = exp.get("P_graph") if graph_available else None
    if p_ae is not None:
        p_ae = float(p_ae)
    if p_graph is not None:
        p_graph = float(p_graph)
    structuring = exp.get("structuring_flag")
    return {
        "transaction_id": result["transaction_id"],
        "risk_score": score_100 / 100.0,
        "risk_tier": tier,
        "canonical_decision": decision,
        "canonical_risk_score": score_100,
        "action": action,
        "P_xgb": p_ml,
        "P_ae": p_ae,
        "P_graph": p_graph,
        "P_hybrid": score_100 / 100.0,
        "structuring_flag": None if structuring is None else bool(structuring),
        "ae_available": ae_available,
        "graph_available": graph_available,
        "structuring_available": graph_available,
        "ml_available": ml_available,
        "top_contributing_features": hits[:5],
        "contributions": hits,
        "action_required": tier != "ALLOW",
    }
