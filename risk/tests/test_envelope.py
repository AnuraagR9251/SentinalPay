from datetime import datetime, timezone
from pathlib import Path

from risk.config import RiskConfig
from risk.envelope import attach_public_envelope
from risk.ml_layer import reset_model
from risk.pipeline import evaluate_transaction
from risk.store import RiskStore


def test_envelope_hides_fallback_prior() -> None:
    out = attach_public_envelope(
        {
            "transaction_id": "tx-1",
            "engine_version": "sentinelpay_v1",
            "processing_ms": 4.2,
            "decision": "REVIEW",
            "ml": {"available": False, "fraud_probability": 0.5, "error": "missing_file"},
            "rules": {"triggered_rules": [{"rule": "NEW_DEVICE", "score": 15}]},
        }
    )
    assert out["model_available"] is False
    assert out["model_probability"] is None
    assert "ML_UNAVAILABLE" in out["reason_codes"]
    assert out["policy_version"] == "sentinelpay_v1"
    assert out["inference_latency_ms"] == 4.2
    assert out["triggered_signals"][0]["name"] == "NEW_DEVICE"


def test_envelope_marks_uncalibrated_paysim() -> None:
    out = attach_public_envelope(
        {
            "transaction_id": "tx-uc",
            "engine_version": "sentinelpay_v1",
            "processing_ms": 3.0,
            "ml": {
                "available": True,
                "fraud_probability": 0.9996,
                "calibrated_for_upi": False,
                "evaluation": "synthetic_paysim",
            },
            "rules": {"triggered_rules": []},
            "policy_overrides": ["ROUTINE_SMALL_ALLOW"],
        }
    )
    assert out["model_probability"] == 0.9996
    assert "ML_UNCALIBRATED_PAYSIM" in out["reason_codes"]
    assert "ROUTINE_SMALL_ALLOW" in out["reason_codes"]


def test_envelope_genuine_probability() -> None:
    out = attach_public_envelope(
        {
            "transaction_id": "tx-2",
            "engine_version": "sentinelpay_v1",
            "processing_ms": 3.0,
            "ml": {"available": True, "fraud_probability": 0.81},
            "rules": {"triggered_rules": []},
        }
    )
    assert out["model_available"] is True
    assert out["model_probability"] == 0.81


def test_evaluate_exposes_envelope_aliases(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SENTINALPAY_XGB_MODEL", str(tmp_path / "absent.pkl"))
    reset_model()
    try:
        store = RiskStore(tmp_path / "env.db")
        result = evaluate_transaction(
            {
                "transaction_id": "tx-env-1",
                "user_id": "USR_ENV",
                "amount": 200,
                "merchant_id": "kirana@oksbi",
                "merchant_category": "groceries",
                "timestamp": datetime(2026, 9, 28, 11, 0, tzinfo=timezone.utc).isoformat(),
            },
            store=store,
            config=RiskConfig(),
        )
        assert "model_probability" in result
        assert result["model_available"] is False
        assert result["model_probability"] is None
        assert result["policy_version"]
        assert isinstance(result["reason_codes"], list)
        assert isinstance(result["inference_latency_ms"], float)
    finally:
        monkeypatch.delenv("SENTINALPAY_XGB_MODEL", raising=False)
        reset_model()
