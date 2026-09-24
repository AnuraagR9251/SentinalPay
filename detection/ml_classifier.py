"""Inference wrapper for the trained payment-risk model.

The model is loaded once (read-only). `classify_payment` is then a pure
function of the transaction. If artefacts are missing, it returns None
so the rule engine still works.

# TODO: apply rate limiting here before production use
# TODO: persist via parameterized queries / ORM only — never string-formatted SQL
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np

from detection.models import PaymentRiskLabel, Transaction
from ml.features import ID_TO_LABEL, vector_from_transaction

logger = logging.getLogger("sentinalpay.ml")

ARTIFACT_DIR = Path(__file__).resolve().parent.parent / "ml" / "artifacts"
MODEL_PATH = ARTIFACT_DIR / "payment_risk_xgb.json"
META_PATH = ARTIFACT_DIR / "model_meta.json"

_BUNDLE: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class MLPrediction:
    label: PaymentRiskLabel
    probabilities: tuple[tuple[str, float], ...]


def _load_bundle() -> Optional[dict[str, Any]]:
    global _BUNDLE
    if _BUNDLE is not None:
        return _BUNDLE
    if not MODEL_PATH.exists() or not META_PATH.exists():
        logger.warning("ML artefacts missing — classify_payment disabled until `py -3 -m ml.train`")
        return None
    try:
        import xgboost as xgb

        # Raw booster — avoids sklearn mixin `_estimator_type` after sklearn 1.9.
        booster = xgb.Booster()
        booster.load_model(MODEL_PATH)
        meta = json.loads(META_PATH.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("ML artefacts unreadable: %s", type(exc).__name__)
        return None
    _BUNDLE = {"booster": booster, "meta": meta}
    return _BUNDLE


def reset_model_cache() -> None:
    """Test helper: drop the cached booster so a new artefact can be loaded."""
    global _BUNDLE
    _BUNDLE = None


def classify_payment(transaction: Transaction) -> Optional[MLPrediction]:
    """Return LEGIT / SUSPICIOUS / LIKELY_FRAUD, or None if no model is present."""
    bundle = _load_bundle()
    if bundle is None:
        return None
    import xgboost as xgb

    medians = bundle["meta"].get("category_medians") or {}
    vector = vector_from_transaction(transaction, category_medians=medians)
    try:
        raw = bundle["booster"].predict(xgb.DMatrix(vector.reshape(1, -1)))
        proba = np.asarray(raw, dtype=np.float64).reshape(-1)
    except (TypeError, ValueError) as exc:
        logger.warning("ML inference unavailable: %s", type(exc).__name__)
        return None
    winner = int(np.argmax(proba))
    label_name = bundle["meta"].get("id_to_label", ID_TO_LABEL).get(str(winner))
    if label_name is None:
        label_name = ID_TO_LABEL[winner]
    pairs = tuple(
        (ID_TO_LABEL[idx], float(proba[idx]))
        for idx in range(len(proba))
    )
    return MLPrediction(label=PaymentRiskLabel(label_name), probabilities=pairs)
