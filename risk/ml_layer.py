"""ML inference only. Training stays in ml/. Same feature names as train."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Sequence

import numpy as np

from detection.scoring_engine import FEATURE_VECTOR_NAMES, extract_feature_vector
from detection.validation import ScoringValidationError
from risk.contracts import MlResult, NormalizedTransaction

REPO_ROOT = Path(__file__).resolve().parent.parent
_MODEL: Any = None
_MODEL_VERSION = "unavailable"
_LOAD_ERROR: str | None = None
# ponytail: 0.5 is a documented conservative prior (not "safe"). Upgrade: calibrated class prior from production traffic.
MISSING_MODEL_PRIOR = 0.5
XGB_EVALUATION = "synthetic_paysim"
UNCALIBRATED_NOTE = "PaySim-trained; not a UPI-calibrated probability"
_MISSING = object()
_SAVED_FEATURE_NAMES: tuple[str, ...] | None = None

# Train and infer use this order. First 10 come from extract_feature_vector.
# PaySim CASH_OUT / full-drain flags are omitted — they encode the simulator's
# fraud recipe, not a general UPI pattern.
# hour_of_day is wall-clock hour/23. On PaySim, timestamp is epoch+step hours,
# so that column tracks simulator time clusters, not UPI circadian risk.
LIVE_FEATURE_NAMES: tuple[str, ...] = FEATURE_VECTOR_NAMES + (
    "hour_of_day",
    "amount_to_median",
    "amount_spike",
    "velocity_1m",
    "velocity_5m_value",
    "velocity_60m_value",
    "new_device",
    "recent_device_change",
    "recipient_prior_count",
    "history_size",
    "missing_device",
    "location_reliable",
)


def reset_model() -> None:
    global _MODEL, _MODEL_VERSION, _LOAD_ERROR, _SAVED_FEATURE_NAMES
    _MODEL = None
    _MODEL_VERSION = "unavailable"
    _LOAD_ERROR = None
    _SAVED_FEATURE_NAMES = None


def _mark_missing(reason: str, version: str) -> None:
    global _MODEL, _MODEL_VERSION, _LOAD_ERROR, _SAVED_FEATURE_NAMES
    _MODEL = _MISSING
    _MODEL_VERSION = version
    _LOAD_ERROR = reason
    _SAVED_FEATURE_NAMES = None


def _load() -> Any:
    global _MODEL, _MODEL_VERSION, _LOAD_ERROR, _SAVED_FEATURE_NAMES
    if _MODEL is _MISSING:
        return None
    if _MODEL is not None:
        return _MODEL
    import os

    import joblib

    override = os.getenv("SENTINALPAY_XGB_MODEL", "").strip()
    path = Path(override) if override else REPO_ROOT / "ml" / "models" / "xgboost_model.pkl"
    if not path.is_absolute():
        path = REPO_ROOT / path
    if not path.exists():
        _mark_missing("missing_file", "unavailable")
        return None
    try:
        loaded = joblib.load(path)
    except Exception:
        _mark_missing("load_error", "error")
        return None
    saved_names: tuple[str, ...] | None = None
    if isinstance(loaded, dict) and "model" in loaded:
        model = loaded.get("model")
        version = str(loaded.get("version") or "xgb_v3")
        raw_names = loaded.get("feature_names")
        if isinstance(raw_names, (list, tuple)):
            saved_names = tuple(str(name) for name in raw_names)
    else:
        model = loaded
        version = "xgb_v3"
    if model is None or not hasattr(model, "predict_proba"):
        _mark_missing("incompatible", "incompatible")
        return None
    n_in = int(getattr(model, "n_features_in_", len(LIVE_FEATURE_NAMES)))
    if n_in != len(LIVE_FEATURE_NAMES):
        _mark_missing("incompatible", "incompatible")
        return None
    if saved_names is not None and saved_names != LIVE_FEATURE_NAMES:
        _mark_missing("incompatible", "incompatible")
        return None
    _MODEL = model
    _MODEL_VERSION = version
    _LOAD_ERROR = None
    _SAVED_FEATURE_NAMES = saved_names or LIVE_FEATURE_NAMES
    return _MODEL


def _as_engine_txn(txn: NormalizedTransaction) -> dict:
    return {
        "transaction_id": txn.transaction_id,
        "user_id": txn.user_id,
        "amount": txn.amount,
        "payee_vpa": txn.merchant_id,
        "timestamp": txn.timestamp,
        "lat": txn.latitude,
        "lon": txn.longitude,
        "device_id": txn.device_id,
        "ip_address": txn.ip_address,
        "purpose": txn.merchant_category,
        "origin_balance": txn.origin_balance,
        "new_origin_balance": txn.new_origin_balance,
    }


def _history_rows(history: Sequence[dict]) -> list[dict]:
    rows = []
    for row in history:
        rows.append(
            {
                "transaction_id": row.get("transaction_id") or "hist",
                "user_id": row.get("user_id") or "unknown",
                "amount": float(row["amount"]),
                "payee_vpa": row.get("merchant_id") or row.get("payee_vpa") or "unknown",
                "timestamp": row["timestamp"],
                "lat": row.get("latitude", row.get("lat")),
                "lon": row.get("longitude", row.get("lon")),
                "device_id": row.get("device_id"),
                "ip_address": row.get("ip_address"),
            }
        )
    return rows


def _as_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _window(txn: NormalizedTransaction, history: Sequence[dict], seconds: float) -> tuple[int, float]:
    count = 1
    value = float(txn.amount)
    t = txn.timestamp
    for row in history:
        delta = (t - _as_dt(row["timestamp"])).total_seconds()
        if 0 <= delta <= seconds:
            count += 1
            value += float(row["amount"])
    return count, value


def model_is_loaded() -> bool:
    try:
        return _load() is not None
    except Exception:
        return False


def model_status() -> dict[str, Any]:
    loaded = model_is_loaded()
    return {
        "model_loaded": loaded,
        "model_version": _MODEL_VERSION if loaded else _MODEL_VERSION or "unavailable",
        "ml_fallback": None if loaded else "conservative_prior_0.5; ALLOW demoted to REVIEW",
        "load_error": None if loaded else _LOAD_ERROR,
        "calibrated_for_upi": False,
        "evaluation": XGB_EVALUATION if loaded else None,
        "experimental": bool(loaded),
        "note": UNCALIBRATED_NOTE if loaded else None,
    }


def engineer_features(
    txn: NormalizedTransaction,
    history: Sequence[dict],
    home: tuple[float, float] | None,
) -> dict[str, float]:
    """Shared feature vector for train and evaluate.

    Missing home / GPS is UNKNOWN — not treated as fraud.
    History is clipped to rows strictly before this payment (no future leak).
    """
    t = txn.timestamp
    history = [row for row in history if _as_dt(row["timestamp"]) < t]
    known = {row.get("merchant_id") or row.get("payee_vpa") for row in history if row.get("merchant_id") or row.get("payee_vpa")}
    profile = {
        "user_id": txn.user_id,
        "home_lat": None if home is None else home[0],
        "home_lon": None if home is None else home[1],
        "known_payees": known,
    }
    try:
        vector = extract_feature_vector(_as_engine_txn(txn), _history_rows(history), profile)
    except ScoringValidationError:
        vector = {name: 0.0 for name in FEATURE_VECTOR_NAMES}

    amounts = [float(row["amount"]) for row in history]
    med = median(amounts) if amounts else 0.0
    if med > 0:
        rel = txn.amount / med
        vector["amount_to_median"] = _clip01(rel / 20.0)
        vector["amount_spike"] = _clip01(rel / 10.0) if rel > 2 else 0.0
    else:
        vector["amount_to_median"] = 0.5
        vector["amount_spike"] = 0.0

    vel_1m, val_1m = _window(txn, history, 60.0)
    _, val_5m = _window(txn, history, 300.0)
    _, val_60m = _window(txn, history, 3600.0)
    scale = med if med > 0 else max(txn.amount, 1.0)
    vector["hour_of_day"] = float(txn.timestamp.hour) / 23.0
    vector["velocity_1m"] = _clip01(vel_1m / 5.0)
    vector["velocity_5m_value"] = _clip01(val_5m / (scale * 8.0))
    vector["velocity_60m_value"] = _clip01(val_60m / (scale * 20.0))

    devices = [str(row.get("device_id")) for row in history if row.get("device_id")]
    vector["missing_device"] = 0.0 if txn.device_id else 1.0
    vector["new_device"] = 1.0 if txn.device_id and str(txn.device_id) not in set(devices) and devices else 0.0
    latest = max(history, key=lambda row: _as_dt(row["timestamp"])) if history else None
    last_dev = str(latest.get("device_id") or "") if latest else ""
    vector["recent_device_change"] = (
        1.0 if txn.device_id and last_dev and str(txn.device_id) != last_dev else 0.0
    )

    prior_payee = sum(1 for row in history if (row.get("merchant_id") or row.get("payee_vpa")) == txn.merchant_id)
    vector["recipient_prior_count"] = _clip01(prior_payee / 10.0)
    vector["history_size"] = _clip01(len(history) / 20.0)

    geo_now = txn.latitude is not None and txn.longitude is not None
    geo_prior = any(row.get("latitude") is not None or row.get("lat") is not None for row in history)
    reliable = bool(geo_now and (geo_prior or home is not None))
    vector["location_reliable"] = 1.0 if reliable else 0.0
    if not reliable:
        vector["dist_from_home"] = 0.0
        vector["dist_from_last"] = 0.0
        vector["impossible_travel"] = 0.0

    return {name: float(vector.get(name, 0.0)) for name in LIVE_FEATURE_NAMES}


def infer_fraud(
    txn: NormalizedTransaction, history: Sequence[dict], home: tuple[float, float] | None
) -> MlResult:
    try:
        vector = engineer_features(txn, history, home)
    except Exception:
        return MlResult(
            fraud_probability=MISSING_MODEL_PRIOR,
            model_version="error",
            features={},
            available=False,
            error="feature_error",
        )
    try:
        model = _load()
    except Exception:
        _mark_missing("load_error", "error")
        model = None
    if model is None:
        reason = _LOAD_ERROR or "unavailable"
        return MlResult(
            fraud_probability=MISSING_MODEL_PRIOR,
            model_version=_MODEL_VERSION or "unavailable",
            features=vector,
            available=False,
            error=reason,
        )
    try:
        x = np.asarray([[vector.get(name, 0.0) for name in LIVE_FEATURE_NAMES]], dtype=np.float32)
        proba = float(model.predict_proba(x)[0, 1])
    except Exception:
        # Fail-safe: prior 0.5, available=False. Aggregate demotes ALLOW → REVIEW.
        return MlResult(
            fraud_probability=MISSING_MODEL_PRIOR,
            model_version="error",
            features=vector,
            available=False,
            error="inference_error",
            calibrated_for_upi=False,
            evaluation=None,
        )
    if not np.isfinite(proba):
        return MlResult(
            fraud_probability=MISSING_MODEL_PRIOR,
            model_version="error",
            features=vector,
            available=False,
            error="inference_error",
            calibrated_for_upi=False,
            evaluation=None,
        )
    return MlResult(
        fraud_probability=max(0.0, min(1.0, proba)),
        model_version=_MODEL_VERSION,
        features=vector,
        available=True,
        calibrated_for_upi=False,
        evaluation=XGB_EVALUATION,
    )
