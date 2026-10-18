"""Missing XGBoost is not treated as zero risk."""

from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from risk.config import RiskConfig
from risk.ml_layer import MISSING_MODEL_PRIOR, infer_fraud, model_status, reset_model
from risk.normalize import normalize_transaction
from risk.pipeline import evaluate_transaction
from risk.store import RiskStore


def test_committed_xgb_v3_artifact_loads() -> None:
    from risk.ml_layer import REPO_ROOT

    path = REPO_ROOT / "ml" / "models" / "xgboost_model.pkl"
    assert path.is_file(), "ml/models/xgboost_model.pkl must be tracked for a clean checkout"
    reset_model()
    try:
        status = model_status()
        assert status["model_loaded"] is True
        assert status["ml_fallback"] is None
        assert status["model_version"]
        assert status["model_version"] != "unavailable"
    finally:
        reset_model()


def test_missing_model_uses_prior_and_blocks_allow(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SENTINALPAY_XGB_MODEL", str(tmp_path / "absent.pkl"))
    reset_model()
    try:
        status = model_status()
        assert status["model_loaded"] is False
        assert status["ml_fallback"]
        txn = normalize_transaction(
            {
                "transaction_id": "miss-1",
                "user_id": "USR_MISS",
                "amount": 200,
                "merchant_id": "kirana@oksbi",
                "timestamp": datetime(2026, 9, 28, 11, 0, tzinfo=timezone.utc).isoformat(),
                "latitude": 12.9716,
                "longitude": 77.5946,
            }
        )
        ml = infer_fraud(txn, [], None)
        assert ml.available is False
        assert ml.fraud_probability == MISSING_MODEL_PRIOR
        store = RiskStore(tmp_path / "miss.db")
        result = evaluate_transaction(
            {
                "transaction_id": "miss-eval-1",
                "user_id": "USR_MISS",
                "amount": 200,
                "merchant_id": "kirana@oksbi",
                "merchant_category": "groceries",
                "timestamp": datetime(2026, 9, 28, 11, 0, tzinfo=timezone.utc).isoformat(),
                "latitude": 12.9716,
                "longitude": 77.5946,
            },
            store=store,
            config=RiskConfig(),
        )
        assert result["decision"] != "ALLOW"
        assert result["ml"]["available"] is False
        reasons = " ".join(item["factor"] for item in result["risk_factors"])
        assert "unavailable" in reasons.lower()
    finally:
        monkeypatch.delenv("SENTINALPAY_XGB_MODEL", raising=False)
        reset_model()


def test_inference_error_uses_prior_not_zero(monkeypatch, tmp_path: Path) -> None:
    class Boom:
        n_features_in_ = 2

        def predict_proba(self, x):
            raise RuntimeError("broken booster")

    monkeypatch.setattr("risk.ml_layer._load", lambda: Boom())
    txn = normalize_transaction(
        {
            "transaction_id": "boom-1",
            "user_id": "USR_BOOM",
            "amount": 200,
            "merchant_id": "kirana@oksbi",
            "timestamp": datetime(2026, 9, 28, 11, 0, tzinfo=timezone.utc).isoformat(),
        }
    )
    ml = infer_fraud(txn, [], None)
    assert ml.available is False
    assert ml.fraud_probability == MISSING_MODEL_PRIOR
    assert ml.fraud_probability != 0.0
    assert ml.model_version == "error"
    store = RiskStore(tmp_path / "boom.db")
    result = evaluate_transaction(
        {
            "transaction_id": "boom-eval-1",
            "user_id": "USR_BOOM",
            "amount": 200,
            "merchant_id": "kirana@oksbi",
            "merchant_category": "groceries",
            "timestamp": datetime(2026, 9, 28, 11, 0, tzinfo=timezone.utc).isoformat(),
        },
        store=store,
        config=RiskConfig(),
    )
    assert result["decision"] != "ALLOW"
    assert result["ml"]["available"] is False
    assert result["ml"].get("error") == "inference_error"


def _txn(txn_id: str = "ml-1") -> dict:
    return {
        "transaction_id": txn_id,
        "user_id": "USR_ML",
        "amount": 200,
        "merchant_id": "kirana@oksbi",
        "timestamp": datetime(2026, 9, 28, 11, 0, tzinfo=timezone.utc).isoformat(),
    }


def test_corrupt_model_file_is_not_zero(tmp_path: Path, monkeypatch) -> None:
    bad = tmp_path / "corrupt.pkl"
    bad.write_bytes(b"this is not a joblib model")
    monkeypatch.setenv("SENTINALPAY_XGB_MODEL", str(bad))
    reset_model()
    try:
        ml = infer_fraud(normalize_transaction(_txn("corrupt-1")), [], None)
        assert ml.available is False
        assert ml.fraud_probability == MISSING_MODEL_PRIOR
        assert ml.model_version == "error"
        status = model_status()
        assert status["model_loaded"] is False
        assert status["load_error"] == "load_error"
    finally:
        monkeypatch.delenv("SENTINALPAY_XGB_MODEL", raising=False)
        reset_model()


def test_deserialization_exception(tmp_path: Path, monkeypatch) -> None:
    import joblib

    path = tmp_path / "boom.pkl"
    path.write_bytes(b"x")
    monkeypatch.setenv("SENTINALPAY_XGB_MODEL", str(path))

    def boom(*_args, **_kwargs):
        raise RuntimeError("unpickle failed")

    monkeypatch.setattr(joblib, "load", boom)
    reset_model()
    try:
        ml = infer_fraud(normalize_transaction(_txn("deser-1")), [], None)
        assert ml.available is False
        assert ml.fraud_probability != 0.0
        assert ml.error == "load_error"
        assert model_status()["model_loaded"] is False
    finally:
        monkeypatch.delenv("SENTINALPAY_XGB_MODEL", raising=False)
        reset_model()


def test_incompatible_model_object(tmp_path: Path, monkeypatch) -> None:
    import joblib

    path = tmp_path / "plain.pkl"
    joblib.dump({"version": "xgb_v3"}, path)
    monkeypatch.setenv("SENTINALPAY_XGB_MODEL", str(path))
    reset_model()
    try:
        ml = infer_fraud(normalize_transaction(_txn("incompat-1")), [], None)
        assert ml.available is False
        assert ml.model_version == "incompatible"
        assert ml.fraud_probability == MISSING_MODEL_PRIOR
    finally:
        monkeypatch.delenv("SENTINALPAY_XGB_MODEL", raising=False)
        reset_model()


def test_valid_model_output(monkeypatch) -> None:
    class Tiny:
        n_features_in_ = 2

        def predict_proba(self, x):
            return np.asarray([[0.25, 0.75]])

    monkeypatch.setattr("risk.ml_layer._load", lambda: Tiny())
    ml = infer_fraud(normalize_transaction(_txn("ok-1")), [], None)
    assert ml.available is True
    assert abs(ml.fraud_probability - 0.75) < 1e-6
    assert ml.error is None


def test_missing_model_does_not_block_independent_rules(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SENTINALPAY_XGB_MODEL", str(tmp_path / "absent.pkl"))
    reset_model()
    try:
        store = RiskStore(tmp_path / "rules.db")
        result = evaluate_transaction(
            {
                "transaction_id": "rule-block-1",
                "user_id": "USR_RULE",
                "amount": 200000,
                "merchant_id": "casino@okaxis",
                "merchant_category": "gambling",
                "timestamp": datetime(2026, 9, 28, 11, 0, tzinfo=timezone.utc).isoformat(),
            },
            store=store,
            config=RiskConfig(),
        )
        names = {item["rule"] for item in result["rules"]["triggered_rules"]}
        assert "HIGH_RISK_MERCHANT" in names
        assert result["ml"]["available"] is False
        assert result["decision"] != "ALLOW"
    finally:
        monkeypatch.delenv("SENTINALPAY_XGB_MODEL", raising=False)
        reset_model()
