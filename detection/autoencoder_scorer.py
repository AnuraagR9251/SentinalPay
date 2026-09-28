"""Unsupervised anomaly score from the trained autoencoder.

The Keras model and threshold are loaded once at import. Scoring copies
the caller's vector and never mutates it.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from detection.scoring_engine import FEATURE_VECTOR_NAMES

logger = logging.getLogger("sentinalpay.ae")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = REPO_ROOT / "ml" / "models" / "autoencoder_model.keras"
DEFAULT_THRESHOLD = REPO_ROOT / "ml" / "models" / "autoencoder_threshold.json"

_MODEL: Any = None
_THRESHOLD: float = 0.0
_LOADED: bool = False


def _paths() -> tuple[Path, Path]:
    model_raw = os.getenv("SENTINALPAY_AE_MODEL", "").strip()
    thr_raw = os.getenv("SENTINALPAY_AE_THRESHOLD", "").strip()
    model_path = Path(model_raw) if model_raw else DEFAULT_MODEL
    thr_path = Path(thr_raw) if thr_raw else DEFAULT_THRESHOLD
    if not model_path.is_absolute():
        model_path = REPO_ROOT / model_path
    if not thr_path.is_absolute():
        thr_path = REPO_ROOT / thr_path
    return model_path, thr_path


def _load() -> None:
    global _MODEL, _THRESHOLD, _LOADED
    if _LOADED:
        return
    _LOADED = True
    model_path, thr_path = _paths()
    if not model_path.exists() or not thr_path.exists():
        logger.warning("autoencoder artefacts missing — score_autoencoder returns 0")
        return
    try:
        from tensorflow import keras

        _MODEL = keras.models.load_model(model_path)
        payload = json.loads(thr_path.read_text(encoding="utf-8"))
        _THRESHOLD = float(payload.get("threshold") or 0.0)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        logger.warning("autoencoder load failed: %s", type(exc).__name__)
        _MODEL = None
        _THRESHOLD = 0.0


def _as_row(feature_vector: Mapping[str, Any] | Sequence[float]) -> np.ndarray:
    if isinstance(feature_vector, Mapping):
        values = [float(feature_vector.get(name, 0.0)) for name in FEATURE_VECTOR_NAMES]
    else:
        values = [float(item) for item in feature_vector]
        if len(values) != len(FEATURE_VECTOR_NAMES):
            raise ValueError("feature_vector width does not match FEATURE_VECTOR_NAMES")
    return np.asarray([values], dtype=np.float32)


def score_autoencoder(feature_vector: Mapping[str, Any] | Sequence[float]) -> float:
    """Return a 0–1 anomaly score. Does not mutate `feature_vector`."""
    _load()
    if _MODEL is None or _THRESHOLD <= 0:
        return 0.0
    row = _as_row(feature_vector)
    predicted = _MODEL.predict(row, verbose=0)
    error = float(np.mean(np.square(row - predicted)))
    return min(1.0, error / _THRESHOLD)


__all__ = ["score_autoencoder"]
