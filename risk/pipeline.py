"""Orchestrate layers. The API route only calls evaluate_transaction."""

from __future__ import annotations

import time
from typing import Any, Mapping, Sequence

from detection.features.location import haversine_km
from risk.aggregate import aggregate_and_decide
from risk.ato import merge_ato
from risk.behavior import analyze_behavior
from risk.config import RiskConfig
from risk.contracts import NormalizedTransaction
from risk.envelope import attach_public_envelope
from risk.ml_layer import infer_fraud
from risk.normalize import NormalizationError, normalize_transaction
from risk.rules import run_rules
from risk.security import inspect_security
from risk.policy import policy_action
from risk.store import RiskStore, get_store

# ponytail: 50 km city-corridor heuristic. Upgrade: per-user commute ellipsoid from stored fixes.
_USUAL_RADIUS_KM = 50.0


class PipelineError(ValueError):
    pass


def _home_from_history(history: Sequence[dict]) -> tuple[float, float] | None:
    """Centroid of prior GPS fixes. Fewer than 2 points → UNKNOWN baseline."""
    points: list[tuple[float, float]] = []
    for row in history:
        lat, lon = row.get("latitude"), row.get("longitude")
        if lat is None or lon is None:
            continue
        points.append((float(lat), float(lon)))
    if len(points) < 2:
        return None
    return (
        sum(item[0] for item in points) / len(points),
        sum(item[1] for item in points) / len(points),
    )


def _location_baseline(txn: NormalizedTransaction, home: tuple[float, float] | None) -> str:
    """Classify geography. Missing history is UNKNOWN, not fraud."""
    if home is None or txn.latitude is None or txn.longitude is None:
        return "UNKNOWN"
    dist = haversine_km(home[0], home[1], txn.latitude, txn.longitude)
    if dist <= _USUAL_RADIUS_KM:
        return "KNOWN_NORMAL_LOCATION"
    return "KNOWN_UNUSUAL_LOCATION"


def _result_payload(
    *,
    txn_id: str,
    user_id: str,
    decision,
    security,
    rules,
    behavior,
    ml,
    location_baseline: str,
    engine_version: str,
    elapsed_ms: float,
) -> dict[str, Any]:
    payload = {
        "transaction_id": txn_id,
        "user_id": user_id,
        "risk_score": decision.risk_score,
        "decision": decision.decision,
        "confidence": decision.confidence,
        "fraud_probability": round(ml.fraud_probability, 4),
        "model_version": ml.model_version,
        "engine_version": engine_version,
        "processing_ms": round(elapsed_ms, 1),
        "processing_time_ms": round(elapsed_ms, 1),
        "location_baseline": location_baseline,
        "security": {
            "duplicate_transaction": security.duplicate_transaction,
            "replay_detected": security.replay_detected,
            "invalid_request": security.invalid_request,
            "rate_limited": security.rate_limited,
            "security_risk_score": security.security_risk_score,
        },
        "rules": {
            "rule_score": rules.rule_score,
            "triggered_rules": [
                {"rule": r.rule, "severity": r.severity, "score": r.score, "reason": r.reason}
                for r in rules.triggered_rules
            ],
        },
        "behavior": {
            "behavioral_score": behavior.behavioral_score,
            "anomalies": [
                {"feature": a.feature, "severity": a.severity, "deviation": a.deviation}
                for a in behavior.anomalies
            ],
        },
        "ml": {
            "fraud_probability": round(ml.fraud_probability, 4),
            "model_version": ml.model_version,
            "available": ml.available,
            "error": ml.error,
        },
        "policy": dict(decision.policy),
        "risk_factors": [{"factor": f.factor, "impact": f.impact} for f in decision.risk_factors],
        "components": {k: round(v, 2) for k, v in decision.components.items()},
    }
    return attach_public_envelope(payload)


def evaluate_transaction(
    raw: Mapping[str, Any],
    *,
    client_key: str = "local",
    store: RiskStore | None = None,
    config: RiskConfig | None = None,
    session_token: str | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    cfg = config or RiskConfig.load()
    db = store or get_store()
    try:
        txn = normalize_transaction(raw)
    except NormalizationError as exc:
        raise PipelineError(str(exc)) from exc

    cached = db.get_result(txn.transaction_id)
    if cached is not None:
        replay = dict(cached)
        replay["idempotent"] = True
        security = replay.get("security")
        if isinstance(security, dict):
            security = dict(security)
            security["duplicate_transaction"] = True
            replay["security"] = security
        replay["action"] = replay.get("action") or policy_action(replay)
        return attach_public_envelope(replay)

    security = inspect_security(txn, db, cfg, client_key=client_key)
    history = db.user_history(txn.user_id)
    home = _home_from_history(history)
    location_baseline = _location_baseline(txn, home)
    rules = merge_ato(run_rules(txn, history, cfg), security)
    behavior = analyze_behavior(txn, history)
    ml = infer_fraud(txn, history, home)
    decision = aggregate_and_decide(security, rules, behavior, ml, cfg)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    result = _result_payload(
        txn_id=txn.transaction_id,
        user_id=txn.user_id,
        decision=decision,
        security=security,
        rules=rules,
        behavior=behavior,
        ml=ml,
        location_baseline=location_baseline,
        engine_version=cfg.engine_version,
        elapsed_ms=elapsed_ms,
    )
    result["action"] = policy_action(result)
    wrote = db.persist(txn, security, rules, behavior, ml, decision, cfg.engine_version, elapsed_ms, result=result)
    if wrote is False:
        cached = db.get_result(txn.transaction_id)
        if cached is not None:
            replay = dict(cached)
            replay["idempotent"] = True
            replay["action"] = replay.get("action") or policy_action(replay)
            return attach_public_envelope(replay)
    if result.get("action") == "STEP_UP":
        challenge = db.create_challenge(txn.user_id, txn.transaction_id, session_token)
        result["challenge_id"] = challenge["challenge_id"]
        result["challenge_kind"] = "sandbox_pin"
        result["challenge_note"] = "Sandbox PIN confirmation, not bank OTP"
        db.update_result_json(txn.transaction_id, result)
    return attach_public_envelope(result)
