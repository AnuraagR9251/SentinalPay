"""Deterministic HOLD resolution. Not a second fraud model and not an accuracy claim.

Runs only after the primary policy already returned HOLD. It never rescores
XGBoost and never changes ALLOW, STEP_UP, or BLOCK. Missing evidence stays
missing: it cannot approve, and it is not treated as safe.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from detection.features.location import haversine_km
from risk.policy import SERIOUS_RULES

# ponytail: fixed cuts on observed history, not a trained ranker.
# Upgrade path: replace the cuts with a measured policy on labeled hold outcomes.
MIN_PRIOR = 5
AMOUNT_REJECT_MULTIPLE = 3
VELOCITY_WINDOW_S = 300
VELOCITY_REJECT_COUNT = 5
FAILURE_REJECT_COUNT = 3
LOCATION_APPROVE_KM = 50
SPEED_REJECT_KMH = 800
APPROVAL_TTL_S = 15 * 60
OUTCOMES = ("APPROVE", "REJECT", "CONTINUE_HOLD", "STEP_UP")


def _dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _coord(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return round(float(value), 5)
    except (TypeError, ValueError):
        return None


def same_binding(stored: Mapping[str, Any], incoming: Mapping[str, Any]) -> bool:
    """Critical checkout fields are part of the stored decision."""
    return (
        str(stored.get("user_id") or "") == str(incoming.get("user_id") or "")
        and int(stored.get("amount_paise") or 0) == int(incoming.get("amount_paise") or 0)
        and str(stored.get("currency") or "") == str(incoming.get("currency") or "")
        and str(stored.get("merchant_id") or "") == str(incoming.get("merchant_id") or "")
        and str(stored.get("device_id") or "") == str(incoming.get("device_id") or "")
        and _coord(stored.get("latitude")) == _coord(incoming.get("latitude"))
        and _coord(stored.get("longitude")) == _coord(incoming.get("longitude"))
    )


def _amounts(priors: list[Mapping[str, Any]]) -> list[float] | None:
    values: list[float] = []
    for row in priors:
        if row.get("amount") is None:
            continue
        try:
            values.append(float(row["amount"]))
        except (TypeError, ValueError):
            continue
    if len(values) < MIN_PRIOR:
        return None
    return values


def _velocity(priors: list[Mapping[str, Any]], timestamp: Any) -> int | None:
    current = _dt(timestamp)
    if current is None:
        return None
    seen = 0
    count = 0
    for row in priors:
        prior = _dt(row.get("timestamp"))
        if prior is None:
            continue
        seen += 1
        delta = (current - prior).total_seconds()
        if 0 <= delta <= VELOCITY_WINDOW_S:
            count += 1
    if seen < MIN_PRIOR:
        return None
    return count


def _location(priors: list[Mapping[str, Any]], latitude: Any, longitude: Any, timestamp: Any) -> str:
    lat, lon = _coord(latitude), _coord(longitude)
    current = _dt(timestamp)
    if lat is None or lon is None or current is None:
        return "unavailable"
    points: list[tuple[datetime, float, float]] = []
    for row in priors:
        plat, plon = _coord(row.get("latitude")), _coord(row.get("longitude"))
        prior = _dt(row.get("timestamp"))
        if plat is None or plon is None or prior is None:
            continue
        points.append((prior, plat, plon))
    if len(points) < 2:
        return "unavailable"
    points.sort(key=lambda item: item[0])
    last_at, last_lat, last_lon = points[-1]
    distance = haversine_km(last_lat, last_lon, lat, lon)
    delta_h = (current - last_at).total_seconds() / 3600
    if delta_h < 0:
        return "unavailable"
    if delta_h == 0:
        if distance > 1:
            return "inconsistent"
    elif distance / delta_h > SPEED_REJECT_KMH:
        return "inconsistent"
    center_lat = sum(item[1] for item in points) / len(points)
    center_lon = sum(item[2] for item in points) / len(points)
    if haversine_km(center_lat, center_lon, lat, lon) <= LOCATION_APPROVE_KM:
        return "ok"
    return "unusual"


def assess_secondary(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """One of APPROVE, REJECT, CONTINUE_HOLD. Does not read a model score."""
    rejects: list[str] = []
    gaps: list[str] = []
    rules = evidence.get("triggered_rules", None)
    if isinstance(rules, list) and any(str(name) in SERIOUS_RULES for name in rules):
        rejects.append("serious_primary_rule")
    recent = evidence.get("recent_failures", None)
    failed = evidence.get("failed_payments", None)
    if isinstance(recent, int) and not isinstance(recent, bool) and recent >= FAILURE_REJECT_COUNT:
        rejects.append("failed_attempts")
    if isinstance(failed, int) and not isinstance(failed, bool) and failed >= FAILURE_REJECT_COUNT:
        rejects.append("failed_payments")

    history = evidence.get("history", None)
    if not isinstance(history, list) or len(history) < MIN_PRIOR:
        gaps.append("missing_history")
    else:
        amounts = _amounts(history)
        try:
            amount = float(evidence["amount"])
        except (KeyError, TypeError, ValueError):
            amount = None
        if amounts is None or amount is None:
            gaps.append("history_amounts_unavailable")
        elif amount > AMOUNT_REJECT_MULTIPLE * max(amounts):
            rejects.append("amount_deviation")
        elif amount > max(amounts):
            gaps.append("amount_above_history")
        velocity = _velocity(history, evidence.get("timestamp"))
        if velocity is None:
            gaps.append("velocity_unavailable")
        elif velocity >= VELOCITY_REJECT_COUNT:
            rejects.append("velocity")
        device_id = str(evidence.get("device_id") or "")
        known_devices = {str(row.get("device_id") or "") for row in history if row.get("device_id")}
        if not device_id:
            gaps.append("device_unavailable")
        elif device_id not in known_devices:
            gaps.append("new_device")
        merchant_id = str(evidence.get("merchant_id") or "")
        known_merchants = {str(row.get("merchant_id") or "") for row in history if row.get("merchant_id")}
        if not merchant_id or merchant_id not in known_merchants:
            gaps.append("new_payee")
        location = _location(history, evidence.get("latitude"), evidence.get("longitude"), evidence.get("timestamp"))
        if location == "inconsistent":
            rejects.append("location_inconsistent")
        elif location == "unusual":
            gaps.append("location_unusual")
        elif location != "ok":
            gaps.append("location_unavailable")

    if evidence.get("model_available") is not True:
        gaps.append("model_unavailable")
    if not isinstance(rules, list):
        gaps.append("rules_unavailable")
    observed_failure = False
    if isinstance(recent, int) and not isinstance(recent, bool):
        observed_failure = True
        if 0 < recent < FAILURE_REJECT_COUNT:
            gaps.append("prior_failures")
    if isinstance(failed, int) and not isinstance(failed, bool):
        observed_failure = True
        if 0 < failed < FAILURE_REJECT_COUNT:
            gaps.append("prior_failures")
    if not observed_failure:
        gaps.append("failures_unavailable")

    if evidence.get("graph_state") == "strong":
        rejects.append("graph_network")
    ae_strong = evidence.get("ae_state") == "strong"
    if rejects:
        return {"outcome": "REJECT", "reasons": rejects}
    if gaps:
        if ae_strong:
            gaps.append("ae_anomaly")
        return {"outcome": "CONTINUE_HOLD", "reasons": gaps}
    if ae_strong:
        return {"outcome": "STEP_UP", "reasons": ["ae_anomaly"]}
    reasons = ["history_consistent"]
    if evidence.get("ae_state") == "normal":
        reasons.append("ae_normal")
    if evidence.get("graph_state") == "normal":
        reasons.append("graph_normal")
    return {"outcome": "APPROVE", "reasons": reasons}


def _rule_names(result: Mapping[str, Any]) -> list[str] | None:
    rules = result.get("rules")
    if not isinstance(rules, dict) or "triggered_rules" not in rules:
        return None
    names: list[str] = []
    for item in rules.get("triggered_rules") or []:
        if isinstance(item, dict) and item.get("rule"):
            names.append(str(item["rule"]))
        elif isinstance(item, str):
            names.append(item)
    return names


def _model_available(result: Mapping[str, Any]) -> bool | None:
    ml = result.get("ml")
    if not isinstance(ml, dict) or "available" not in ml:
        return None
    return True if ml.get("available") is True else False


def _recent_failures(result: Mapping[str, Any]) -> int | None:
    if "recent_failures" not in result:
        return None
    value = result.get("recent_failures")
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _signal_state(experimental: Mapping[str, Any] | None, kind: str) -> str:
    from risk.fusion import fuse_decision

    fused = fuse_decision("ALLOW", experimental if isinstance(experimental, Mapping) else {})
    return str(fused.get(kind) or "unavailable")


def collect_evidence(store: Any, result: Mapping[str, Any], fields: Mapping[str, Any]) -> dict[str, Any]:
    transaction_id = str(result.get("transaction_id") or fields.get("transaction_id") or "")
    user_id = str(fields.get("user_id") or "")
    history = [
        row
        for row in store.user_history(user_id)
        if str(row.get("transaction_id") or "") != transaction_id
    ]
    return {
        "amount": round(int(fields["amount_paise"]) / 100, 2),
        "history": history,
        "device_id": str(fields.get("device_id") or ""),
        "merchant_id": str(fields.get("merchant_id") or ""),
        "latitude": fields.get("latitude"),
        "longitude": fields.get("longitude"),
        "timestamp": fields.get("timestamp"),
        "triggered_rules": _rule_names(result),
        "model_available": _model_available(result),
        "recent_failures": _recent_failures(result),
        "failed_payments": store.failed_checkout_count(user_id, exclude_transaction_id=transaction_id),
        "ae_state": _signal_state(result.get("experimental"), "ae_state"),
        "graph_state": _signal_state(result.get("experimental"), "graph_state"),
    }


def resolve_hold(store: Any, result: Mapping[str, Any], fields: Mapping[str, Any]) -> dict[str, Any]:
    """Bind one secondary decision to this transaction. Replay returns the same row."""
    transaction_id = str(result.get("transaction_id") or fields.get("transaction_id") or "")
    incoming = {
        "user_id": fields.get("user_id"),
        "amount_paise": fields.get("amount_paise"),
        "currency": fields.get("currency"),
        "merchant_id": fields.get("merchant_id"),
        "device_id": fields.get("device_id") or "",
        "latitude": fields.get("latitude"),
        "longitude": fields.get("longitude"),
    }
    existing = store.get_secondary_assessment(transaction_id) if transaction_id else None
    if existing is not None:
        if not same_binding(existing, incoming):
            return {**existing, "conflict": True}
        return existing
    try:
        if not transaction_id:
            raise ValueError("missing transaction")
        decision = assess_secondary(collect_evidence(store, result, fields))
        outcome = str(decision.get("outcome") or "")
        if outcome not in OUTCOMES:
            raise ValueError("invalid secondary outcome")
        reasons = list(decision.get("reasons") or [])
    except Exception:
        outcome = "CONTINUE_HOLD"
        reasons = ["assessment_failed"]
    score = result.get("risk_score")
    try:
        primary_score = None if score is None else int(score)
    except (TypeError, ValueError):
        primary_score = None
    return store.put_secondary_assessment(
        {
            "transaction_id": transaction_id,
            "user_id": str(fields.get("user_id") or ""),
            "amount_paise": int(fields["amount_paise"]),
            "currency": str(fields.get("currency") or ""),
            "merchant_id": str(fields.get("merchant_id") or ""),
            "device_id": str(fields.get("device_id") or ""),
            "latitude": _coord(fields.get("latitude")),
            "longitude": _coord(fields.get("longitude")),
            "outcome": outcome,
            "reasons": reasons,
            "primary_action": str(result.get("action") or "HOLD"),
            "primary_decision": result.get("decision"),
            "primary_score": primary_score,
            "ttl_s": APPROVAL_TTL_S,
        }
    )
