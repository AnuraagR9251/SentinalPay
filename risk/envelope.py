"""Public evaluate aliases. Existing keys stay; these names are additive."""

from __future__ import annotations

from typing import Any, Mapping


def attach_public_envelope(result: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(result)
    ml = out.get("ml") if isinstance(out.get("ml"), dict) else {}
    if "available" not in ml:
        model_available = None
    else:
        model_available = bool(ml.get("available"))
    if model_available is True:
        raw_p = ml.get("fraud_probability")
        if raw_p is None:
            raw_p = out.get("fraud_probability")
        model_probability = None if raw_p is None else float(raw_p)
    else:
        model_probability = None
    rules = (out.get("rules") or {}).get("triggered_rules") or []
    codes: list[str] = []
    for item in rules:
        name = item.get("rule") if isinstance(item, dict) else None
        if name:
            codes.append(str(name))
    if model_available is False and "ML_UNAVAILABLE" not in codes:
        codes.append("ML_UNAVAILABLE")
    if model_available is True and ml.get("calibrated_for_upi") is False:
        codes.append("ML_UNCALIBRATED_PAYSIM")
    for override in out.get("policy_overrides") or []:
        name = str(override)
        if name and name not in codes:
            codes.append(name)
    security = out.get("security") if isinstance(out.get("security"), dict) else {}
    if security.get("replay_detected"):
        codes.append("REPLAY")
    if security.get("rate_limited"):
        codes.append("RATE_LIMITED")
    signals = [
        {"name": str(item.get("rule") or "signal"), "value": float(item.get("score") or 0) / 100.0}
        for item in rules
        if isinstance(item, dict)
    ]
    latency = out.get("processing_ms")
    if latency is None:
        latency = out.get("processing_time_ms")
    out["model_probability"] = model_probability
    out["model_available"] = model_available
    out["triggered_signals"] = signals
    out["reason_codes"] = codes
    out["policy_version"] = out.get("engine_version")
    out["inference_latency_ms"] = None if latency is None else float(latency)
    return out
