"""ML inference only. Training stays in ml/. Same feature names as /score."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import numpy as np

from detection.scoring_engine import FEATURE_VECTOR_NAMES, extract_feature_vector
from detection.validation import ScoringValidationError
from risk.contracts import MlResult, NormalizedTransaction

REPO_ROOT = Path(__file__).resolve().parent.parent
_MODEL: Any = None
_MODEL_VERSION = "unavailable"


def _load() -> Any:
    global _MODEL, _MODEL_VERSION
    if _MODEL is not None:
        return _MODEL
    if _MODEL_VERSION == "missing":
        return None
    import os

    import joblib

    override = os.getenv("SENTINALPAY_XGB_MODEL", "").strip()
    path = Path(override) if override else REPO_ROOT / "ml" / "models" / "xgboost_model.pkl"
    if not path.is_absolute():
        path = REPO_ROOT / path
    if not path.exists():
        _MODEL_VERSION = "missing"
        return None
    loaded = joblib.load(path)
    _MODEL = loaded["model"] if isinstance(loaded, dict) and "model" in loaded else loaded
    _MODEL_VERSION = "xgb_v1"
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
    }


def _history_rows(history: Sequence[dict]) -> list[dict]:
    rows = []
    for row in history:
        rows.append(
            {
                "transaction_id": row.get("transaction_id") or "hist",
                "user_id": row.get("user_id") or "unknown",
                "amount": float(row["amount"]),
                "payee_vpa": row.get("merchant_id") or "unknown",
                "timestamp": row["timestamp"],
                "lat": row.get("latitude"),
                "lon": row.get("longitude"),
                "device_id": row.get("device_id"),
                "ip_address": row.get("ip_address"),
            }
        )
    return rows


def model_is_loaded() -> bool:
    return _load() is not None


def engineer_features(
    txn: NormalizedTransaction,
    history: Sequence[dict],
    home: tuple[float, float] | None,
) -> dict[str, float]:
    """Shared feature vector for train and evaluate.

    XGBoost here is experimental (synthetic geo leak on the current artefact).
    Missing home is UNKNOWN — not treated as fraud.
    """
    known = {row.get("merchant_id") for row in history if row.get("merchant_id")}
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
    vector["hour_of_day"] = float(txn.timestamp.hour) / 23.0
    vector["is_new_device"] = 1.0 if txn.device_id and txn.device_id not in {r.get("device_id") for r in history} else 0.0
    vector["is_new_merchant"] = 1.0 if txn.merchant_id not in {r.get("merchant_id") for r in history} else 0.0
    return vector


def infer_fraud(
    txn: NormalizedTransaction, history: Sequence[dict], home: tuple[float, float] | None
) -> MlResult:
    vector = engineer_features(txn, history, home)
    model = _load()
    if model is None:
        return MlResult(fraud_probability=0.0, model_version="unavailable", features=vector)
    x = np.asarray([[vector.get(name, 0.0) for name in FEATURE_VECTOR_NAMES]], dtype=np.float32)
    proba = float(model.predict_proba(x)[0, 1])
    return MlResult(fraud_probability=max(0.0, min(1.0, proba)), model_version=_MODEL_VERSION, features=vector)
