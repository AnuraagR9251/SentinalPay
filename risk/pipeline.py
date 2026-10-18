"""Orchestrate layers. The API route only calls evaluate_transaction."""

from __future__ import annotations

import math
import time
from typing import Any, Mapping, Sequence

from detection.autoencoder_scorer import infer_autoencoder
from detection.features.location import haversine_km
from detection.graph_features import (
    GraphValidationError,
    WINDOW_SECONDS,
    add_transaction,
    graph_from_rows,
    graph_signals,
    score_graph,
)
from detection.scoring_engine import extract_feature_vector
from detection.validation import ScoringValidationError
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
from risk.store import RiskStore, StoreConflictError, get_store, payment_identity

# ponytail: 50 km city-corridor heuristic. Upgrade: per-user commute ellipsoid from stored fixes.
_USUAL_RADIUS_KM = 50.0


class PipelineError(ValueError):
    pass


class ConflictError(PipelineError):
    """Same transaction_id reused with different material payment fields."""


_CONFLICT_MSG = "transaction_id already used with different payment details"


def http_status_for_pipeline_error(exc: PipelineError) -> int:
    return 409 if isinstance(exc, ConflictError) else 422


def _replay_or_conflict(db: RiskStore, txn: NormalizedTransaction) -> dict[str, Any] | None:
    stored = db.get_transaction(txn.transaction_id)
    cached = db.get_result(txn.transaction_id)
    if stored is None and cached is None:
        return None
    incoming = payment_identity(txn.user_id, txn.amount, txn.currency, txn.merchant_id)
    if stored is not None:
        existing = payment_identity(
            stored.get("user_id"),
            stored.get("amount"),
            stored.get("currency"),
            stored.get("merchant_id"),
        )
        if existing != incoming:
            raise ConflictError(_CONFLICT_MSG)
    else:
        cached_user = str((cached or {}).get("user_id") or "")
        if cached_user and cached_user != txn.user_id:
            raise ConflictError(_CONFLICT_MSG)
    if cached is None:
        return None
    replay = dict(cached)
    replay["idempotent"] = True
    security = replay.get("security")
    if isinstance(security, dict):
        security = dict(security)
        security["duplicate_transaction"] = True
        replay["security"] = security
    replay["action"] = replay.get("action") or policy_action(replay)
    return attach_public_envelope(replay)


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


_EXPERIMENTAL_NOTE = "experimental; not blended into canonical ALLOW/REVIEW/BLOCK"


def _ae_inputs(
    txn: NormalizedTransaction,
    history: Sequence[dict],
    home: tuple[float, float] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    current = {
        "transaction_id": txn.transaction_id,
        "user_id": txn.user_id,
        "amount": txn.amount,
        "payee_vpa": txn.merchant_id,
        "timestamp": txn.timestamp,
        "lat": txn.latitude,
        "lon": txn.longitude,
        "ip_address": txn.ip_address,
        "device_id": txn.device_id,
        "purpose": txn.merchant_category,
    }
    prior: list[dict[str, Any]] = []
    known: set[str] = set()
    for row in history:
        payee = str(row.get("merchant_id") or "").strip()
        if not payee or row.get("amount") is None or not row.get("timestamp"):
            continue
        known.add(payee)
        prior.append(
            {
                "transaction_id": str(row.get("transaction_id") or "hist"),
                "user_id": txn.user_id,
                "amount": row.get("amount"),
                "payee_vpa": payee,
                "timestamp": row.get("timestamp"),
                "lat": row.get("latitude"),
                "lon": row.get("longitude"),
                "ip_address": row.get("ip_address"),
                "device_id": row.get("device_id"),
            }
        )
    profile = {
        "user_id": txn.user_id,
        "home_lat": None if home is None else home[0],
        "home_lon": None if home is None else home[1],
        "known_payees": known,
    }
    return current, prior, profile


def _experimental_signals(
    txn: NormalizedTransaction,
    history: Sequence[dict],
    home: tuple[float, float] | None,
    db: RiskStore,
) -> dict[str, Any]:
    """AE + graph extras. Failures stay null; they never become 0.0."""
    ae_available = False
    ae_error: str | None = "unavailable"
    p_ae: float | None = None
    try:
        current, prior, profile = _ae_inputs(txn, history, home)
        vector = extract_feature_vector(current, prior, profile)
        ae = infer_autoencoder(vector)
        ae_available = bool(ae.available)
        ae_error = ae.error
        p_ae = None if not ae.available else ae.score
    except (ScoringValidationError, TypeError, ValueError):
        ae_available = False
        ae_error = "feature_error"
        p_ae = None

    graph_available = False
    graph_error: str | None = "unavailable"
    p_graph: float | None = None
    structuring: bool | None = None
    extra: dict[str, Any] = {}
    try:
        rows = db.windowed_transactions(txn.timestamp, WINDOW_SECONDS)
        graph = graph_from_rows(
            rows,
            as_of=txn.timestamp,
            window_s=WINDOW_SECONDS,
            skip_ids={txn.transaction_id},
        )
        try:
            add_transaction(
                graph,
                {
                    "transaction_id": txn.transaction_id,
                    "user_id": txn.user_id,
                    "payee_vpa": txn.merchant_id,
                    "amount": txn.amount,
                    "timestamp": txn.timestamp,
                },
            )
        except GraphValidationError:
            pass
        signals = graph_signals(graph, txn.user_id, as_of=txn.timestamp)
        raw = float(score_graph(graph, txn.user_id, as_of=txn.timestamp))
        if not math.isfinite(raw):
            raise ValueError("non_finite")
        p_graph = min(1.0, max(0.0, raw))
        graph_available = True
        graph_error = None
        structuring = bool(signals["structuring_flag"])
        extra = {
            "mule_cluster": bool(signals["mule_cluster"]),
            "fan_in_count": int(signals["fan_in_count"]),
            "fan_out_count": int(signals["fan_out_count"]),
            "cluster_size": int(signals["cluster_size"]),
        }
    except Exception:
        graph_available = False
        graph_error = "unavailable"
        p_graph = None
        structuring = None
        extra = {}

    return {
        "ae_available": ae_available,
        "ae_error": ae_error,
        "P_ae": p_ae,
        "graph_available": graph_available,
        "graph_error": graph_error,
        "P_graph": p_graph,
        "structuring_flag": structuring,
        "note": _EXPERIMENTAL_NOTE,
        **extra,
    }


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
    experimental: dict[str, Any] | None = None,
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
        "experimental": experimental or {
            "ae_available": False,
            "P_ae": None,
            "graph_available": False,
            "P_graph": None,
            "structuring_flag": None,
            "note": _EXPERIMENTAL_NOTE,
        },
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

    replay = _replay_or_conflict(db, txn)
    if replay is not None:
        return replay

    security = inspect_security(txn, db, cfg, client_key=client_key)
    history = db.user_history(txn.user_id)
    home = _home_from_history(history)
    location_baseline = _location_baseline(txn, home)
    rules = merge_ato(run_rules(txn, history, cfg), security)
    behavior = analyze_behavior(txn, history)
    ml = infer_fraud(txn, history, home)
    decision = aggregate_and_decide(security, rules, behavior, ml, cfg)
    experimental = _experimental_signals(txn, history, home, db)
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
        experimental=experimental,
    )
    result["action"] = policy_action(result)
    try:
        wrote = db.persist(txn, security, rules, behavior, ml, decision, cfg.engine_version, elapsed_ms, result=result)
    except StoreConflictError as exc:
        raise ConflictError(str(exc) or _CONFLICT_MSG) from exc
    if wrote is False:
        replay = _replay_or_conflict(db, txn)
        if replay is not None:
            return replay
        raise ConflictError(_CONFLICT_MSG)
    if result.get("action") == "STEP_UP":
        challenge = db.create_challenge(txn.user_id, txn.transaction_id, session_token)
        result["challenge_id"] = challenge["challenge_id"]
        result["challenge_kind"] = "sandbox_pin"
        result["challenge_note"] = "Sandbox PIN confirmation, not bank OTP"
        db.update_result_json(txn.transaction_id, result)
    return attach_public_envelope(result)
