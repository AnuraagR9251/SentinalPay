"""Missing XGBoost is not treated as zero risk."""

from datetime import datetime, timezone
from pathlib import Path

from risk.config import RiskConfig
from risk.ml_layer import MISSING_MODEL_PRIOR, infer_fraud, model_status, reset_model
from risk.normalize import normalize_transaction
from risk.pipeline import evaluate_transaction
from risk.store import RiskStore


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
