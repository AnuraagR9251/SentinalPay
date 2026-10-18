"""Autoencoder scorer: missing artifacts are None, never a fake 0.0."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from detection.autoencoder_scorer import infer_autoencoder, reset_autoencoder, score_autoencoder
from detection.scoring_engine import FEATURE_VECTOR_NAMES


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    reset_autoencoder()
    yield
    reset_autoencoder()


def _vector() -> list[float]:
    return [0.0] * len(FEATURE_VECTOR_NAMES)


def _threshold_json(path: Path, *, threshold: float = 0.5, names=None) -> Path:
    payload = {
        "threshold": threshold,
        "feature_names": list(FEATURE_VECTOR_NAMES if names is None else names),
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _point(monkeypatch, model: Path, threshold: Path) -> None:
    monkeypatch.setenv("SENTINALPAY_AE_MODEL", str(model))
    monkeypatch.setenv("SENTINALPAY_AE_THRESHOLD", str(threshold))
    reset_autoencoder()


def _tiny_model(tmp_path: Path, width: int):
    pytest.importorskip("tensorflow")
    from tensorflow import keras
    from tensorflow.keras import layers

    model = keras.Sequential(
        [
            layers.Input(shape=(width,)),
            layers.Dense(4, activation="relu"),
            layers.Dense(width, activation="linear"),
        ]
    )
    model.compile(optimizer="adam", loss="mse")
    path = tmp_path / f"ae_{width}.keras"
    model.save(path)
    return path


def test_missing_model_is_none_not_zero(tmp_path, monkeypatch) -> None:
    _point(monkeypatch, tmp_path / "missing.keras", _threshold_json(tmp_path / "thr.json"))
    result = infer_autoencoder(_vector())
    assert result.available is False
    assert result.score is None
    assert result.error == "missing_file"
    assert score_autoencoder(_vector()) is None


def test_missing_threshold(tmp_path, monkeypatch) -> None:
    model = tmp_path / "ae.keras"
    model.write_bytes(b"placeholder")
    _point(monkeypatch, model, tmp_path / "missing.json")
    result = infer_autoencoder(_vector())
    assert result.available is False
    assert result.score is None
    assert result.error == "missing_threshold"


def test_malformed_threshold(tmp_path, monkeypatch) -> None:
    model = tmp_path / "ae.keras"
    model.write_bytes(b"placeholder")
    bad = tmp_path / "thr.json"
    bad.write_text("{not-json", encoding="utf-8")
    _point(monkeypatch, model, bad)
    result = infer_autoencoder(_vector())
    assert result.available is False
    assert result.score is None
    assert result.error == "malformed_threshold"


def test_bad_threshold_rejected(tmp_path, monkeypatch) -> None:
    model = tmp_path / "ae.keras"
    model.write_bytes(b"placeholder")
    _point(monkeypatch, model, _threshold_json(tmp_path / "thr.json", threshold=0.0))
    result = infer_autoencoder(_vector())
    assert result.available is False
    assert result.score is None
    assert result.error == "bad_threshold"


def test_schema_mismatch(tmp_path, monkeypatch) -> None:
    model = tmp_path / "ae.keras"
    model.write_bytes(b"placeholder")
    _point(
        monkeypatch,
        model,
        _threshold_json(tmp_path / "thr.json", names=["only_one"]),
    )
    result = infer_autoencoder(_vector())
    assert result.available is False
    assert result.score is None
    assert result.error == "schema_mismatch"


def test_incompatible_feature_width(tmp_path, monkeypatch) -> None:
    model = _tiny_model(tmp_path, 3)
    _point(monkeypatch, model, _threshold_json(tmp_path / "thr.json"))
    result = infer_autoencoder(_vector())
    assert result.available is False
    assert result.score is None
    assert result.error == "incompatible"


def test_incompatible_vector_length(tmp_path, monkeypatch) -> None:
    model = _tiny_model(tmp_path, len(FEATURE_VECTOR_NAMES))
    _point(monkeypatch, model, _threshold_json(tmp_path / "thr.json"))
    result = infer_autoencoder([0.0, 1.0])
    assert result.available is False
    assert result.score is None
    assert result.error == "incompatible"


def test_repo_artifact_loads_or_reports_missing(monkeypatch) -> None:
    monkeypatch.delenv("SENTINALPAY_AE_MODEL", raising=False)
    monkeypatch.delenv("SENTINALPAY_AE_THRESHOLD", raising=False)
    reset_autoencoder()
    from detection.autoencoder_scorer import DEFAULT_MODEL, ae_status

    status = ae_status()
    if DEFAULT_MODEL.exists():
        assert status["ae_loaded"] is True
        result = infer_autoencoder(_vector())
        assert result.available is True
        assert result.score is not None
        assert math.isfinite(result.score)
        assert 0.0 <= result.score <= 1.0
    else:
        assert status["ae_loaded"] is False
        assert status["ae_error"] == "missing_file"
        assert score_autoencoder(_vector()) is None


def test_successful_inference_is_finite(tmp_path, monkeypatch) -> None:
    model = _tiny_model(tmp_path, len(FEATURE_VECTOR_NAMES))
    _point(monkeypatch, model, _threshold_json(tmp_path / "thr.json", threshold=0.25))
    result = infer_autoencoder(_vector())
    assert result.available is True
    assert result.error is None
    assert result.score is not None
    assert math.isfinite(result.score)
    assert 0.0 <= result.score <= 1.0
