"""Unsupervised reconstruction-error score from the trained autoencoder.

Unavailable / failed loads return score=None. Never a fake 0.0.
The Keras file is optional; missing it is reported, not treated as healthy.
"""

from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from detection.scoring_engine import FEATURE_VECTOR_NAMES

logger = logging.getLogger("sentinalpay.ae")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = REPO_ROOT / "ml" / "models" / "autoencoder_model.keras"
DEFAULT_THRESHOLD = REPO_ROOT / "ml" / "models" / "autoencoder_threshold.json"

_MODEL: Any = None
_THRESHOLD: float | None = None
_LOAD_ERROR: str | None = None
_TRIED: bool = False


@dataclass(frozen=True)
class AeResult:
    available: bool
    score: float | None
    error: str | None
    threshold: float | None = None
    n_features: int | None = None
    note: str = "experimental reconstruction error; not in ALLOW/REVIEW/BLOCK blend"


def reset_autoencoder() -> None:
    global _MODEL, _THRESHOLD, _LOAD_ERROR, _TRIED
    _MODEL = None
    _THRESHOLD = None
    _LOAD_ERROR = None
    _TRIED = False


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


def _read_threshold(thr_path: Path) -> float:
    payload = json.loads(thr_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("threshold json must be an object")
    names = payload.get("feature_names")
    if names is not None and list(names) != list(FEATURE_VECTOR_NAMES):
        raise ValueError("schema_mismatch")
    threshold = float(payload.get("threshold"))
    if not math.isfinite(threshold) or threshold <= 0:
        raise ValueError("bad_threshold")
    return threshold


def _load() -> None:
    global _MODEL, _THRESHOLD, _LOAD_ERROR, _TRIED
    if _TRIED:
        return
    _TRIED = True
    model_path, thr_path = _paths()
    if not model_path.exists():
        _LOAD_ERROR = "missing_file"
        logger.warning("autoencoder model missing at %s", model_path)
        return
    if not thr_path.exists():
        _LOAD_ERROR = "missing_threshold"
        logger.warning("autoencoder threshold missing at %s", thr_path)
        return
    try:
        _THRESHOLD = _read_threshold(thr_path)
    except json.JSONDecodeError:
        _LOAD_ERROR = "malformed_threshold"
        return
    except (TypeError, ValueError) as exc:
        _LOAD_ERROR = "schema_mismatch" if str(exc) == "schema_mismatch" else "bad_threshold"
        return
    try:
        os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
        from tensorflow import keras

        loaded = keras.models.load_model(model_path)
    except ModuleNotFoundError:
        _LOAD_ERROR = "tensorflow_missing"
        _THRESHOLD = None
        return
    except Exception:
        _LOAD_ERROR = "load_error"
        _THRESHOLD = None
        return
    n_in = int(getattr(loaded, "input_shape", (None, len(FEATURE_VECTOR_NAMES)))[-1] or 0)
    if n_in and n_in != len(FEATURE_VECTOR_NAMES):
        _LOAD_ERROR = "incompatible"
        _THRESHOLD = None
        return
    _MODEL = loaded
    _LOAD_ERROR = None


def ae_status() -> dict[str, Any]:
    _load()
    loaded = _MODEL is not None and _THRESHOLD is not None and _LOAD_ERROR is None
    return {
        "ae_loaded": loaded,
        "ae_error": None if loaded else (_LOAD_ERROR or "unavailable"),
        "ae_threshold": _THRESHOLD if loaded else None,
        "ae_note": "experimental; not blended into canonical ALLOW/REVIEW/BLOCK",
    }


def _as_row(feature_vector: Mapping[str, Any] | Sequence[float]) -> np.ndarray:
    if isinstance(feature_vector, Mapping):
        values = [float(feature_vector.get(name, 0.0)) for name in FEATURE_VECTOR_NAMES]
    else:
        values = [float(item) for item in feature_vector]
        if len(values) != len(FEATURE_VECTOR_NAMES):
            raise ValueError("incompatible")
    row = np.asarray([values], dtype=np.float32)
    if not np.all(np.isfinite(row)):
        raise ValueError("non_finite_input")
    return row


def infer_autoencoder(feature_vector: Mapping[str, Any] | Sequence[float]) -> AeResult:
    _load()
    n_feat = len(FEATURE_VECTOR_NAMES)
    if _MODEL is None or _THRESHOLD is None:
        return AeResult(
            available=False,
            score=None,
            error=_LOAD_ERROR or "unavailable",
            n_features=n_feat,
        )
    try:
        row = _as_row(feature_vector)
    except ValueError as exc:
        return AeResult(available=False, score=None, error=str(exc) or "incompatible", n_features=n_feat)
    try:
        predicted = _MODEL.predict(row, verbose=0)
        error = float(np.mean(np.square(row - predicted)))
    except Exception:
        return AeResult(available=False, score=None, error="inference_error", n_features=n_feat)
    if not math.isfinite(error):
        return AeResult(available=False, score=None, error="inference_error", n_features=n_feat)
    score = min(1.0, max(0.0, error / float(_THRESHOLD)))
    return AeResult(
        available=True,
        score=score,
        error=None,
        threshold=float(_THRESHOLD),
        n_features=n_feat,
    )


def score_autoencoder(feature_vector: Mapping[str, Any] | Sequence[float]) -> float | None:
    """0–1 anomaly score, or None when the detector did not run."""
    return infer_autoencoder(feature_vector).score


__all__ = ["AeResult", "ae_status", "infer_autoencoder", "reset_autoencoder", "score_autoencoder"]
