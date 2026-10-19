"""Train/infer schema, aggregate math, and uncalibrated PaySim status."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import joblib
import numpy as np

from risk.aggregate import aggregate_and_decide
from risk.config import RiskConfig
from risk.contracts import BehaviorResult, MlResult, RuleResult, SecuritySignals, TriggeredRule
from risk.ml_layer import (
    LIVE_FEATURE_NAMES,
    UNCALIBRATED_NOTE,
    XGB_EVALUATION,
    engineer_features,
    infer_fraud,
    model_status,
    reset_model,
)
from risk.normalize import normalize_transaction
from risk.pipeline import evaluate_transaction
from risk.store import RiskStore

NOW = datetime(2026, 9, 28, 11, 0, tzinfo=timezone.utc)


def _txn(amount: float, payee: str, *, gps: bool = True, device: str = "dev-1", minutes: int = 0):
    raw = {
        "transaction_id": f"diag-{amount}-{payee}-{minutes}",
        "user_id": "USR_DIAG",
        "amount": amount,
        "merchant_id": payee,
        "timestamp": (NOW + timedelta(minutes=minutes)).isoformat(),
        "device_id": device,
        "merchant_category": "p2p",
    }
    if gps:
        raw["latitude"] = 12.9716
        raw["longitude"] = 77.5946
    return normalize_transaction(raw)


def test_pickle_schema_matches_live_feature_names() -> None:
    path = Path(__file__).resolve().parents[2] / "ml" / "models" / "xgboost_model.pkl"
    loaded = joblib.load(path)
    assert isinstance(loaded, dict)
    assert loaded.get("feature_names") == list(LIVE_FEATURE_NAMES)
    model = loaded["model"]
    assert int(model.n_features_in_) == len(LIVE_FEATURE_NAMES)
    assert list(model.classes_) == [0, 1]


def test_inference_vector_order_matches_training_schema() -> None:
    vector = engineer_features(_txn(1000, "sneha.roy@okaxis"), [], home=None)
    assert list(vector) == list(LIVE_FEATURE_NAMES)
    assert all(isinstance(vector[name], float) and np.isfinite(vector[name]) for name in LIVE_FEATURE_NAMES)
    assert 0.0 <= vector["hour_of_day"] <= 1.0


def test_live_model_returns_finite_probability_in_unit_interval() -> None:
    reset_model()
    try:
        ml = infer_fraud(_txn(240, "kirana@oksbi"), [], None)
        assert ml.available is True
        assert 0.0 <= ml.fraud_probability <= 1.0
        assert np.isfinite(ml.fraud_probability)
        assert ml.calibrated_for_upi is False
        assert ml.evaluation == XGB_EVALUATION
        status = model_status()
        assert status["calibrated_for_upi"] is False
        assert status["evaluation"] == XGB_EVALUATION
        assert status["note"] == UNCALIBRATED_NOTE
    finally:
        reset_model()


def test_ordinary_and_suspicious_demo_rows_both_score(tmp_path: Path) -> None:
    store = RiskStore(tmp_path / "demo.db")
    grocery = evaluate_transaction(
        {
            "transaction_id": "diag-groc",
            "user_id": "USR_DIAG",
            "amount": 240,
            "merchant_id": "kirana@oksbi",
            "merchant_category": "groceries",
            "timestamp": NOW.isoformat(),
            "device_id": "dev-1",
            "latitude": 12.9716,
            "longitude": 77.5946,
        },
        store=store,
        config=RiskConfig(),
    )
    burst = evaluate_transaction(
        {
            "transaction_id": "diag-vel",
            "user_id": "USR_DIAG",
            "amount": 900,
            "merchant_id": "burst@oksbi",
            "merchant_category": "p2p_transfer",
            "timestamp": (NOW + timedelta(seconds=30)).isoformat(),
            "device_id": "dev-1",
            "latitude": 12.9716,
            "longitude": 77.5946,
        },
        store=store,
        config=RiskConfig(),
    )
    for row in (grocery, burst):
        assert row["decision"] in {"ALLOW", "REVIEW", "BLOCK"}
        assert 0 <= row["risk_score"] <= 100
        p = row["ml"]["fraud_probability"]
        assert 0.0 <= p <= 1.0
        assert row["ml"]["calibrated_for_upi"] is False
    assert grocery["experimental"]["note"]
    assert "not blended" in grocery["experimental"]["note"]


def test_missing_model_is_not_a_confident_fraud_score(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SENTINALPAY_XGB_MODEL", str(tmp_path / "absent.pkl"))
    reset_model()
    try:
        ml = infer_fraud(_txn(1000, "sneha.roy@okaxis"), [], None)
        assert ml.available is False
        assert ml.fraud_probability == 0.5
        assert ml.fraud_probability < 0.9
        assert ml.calibrated_for_upi is False
    finally:
        monkeypatch.delenv("SENTINALPAY_XGB_MODEL", raising=False)
        reset_model()


def test_aggregate_matches_hand_calculated_components() -> None:
    cfg = RiskConfig()
    quiet = SecuritySignals(False, False, False, False, 0)
    rules = RuleResult(8, (TriggeredRule("NEW_MERCHANT", "LOW", 8, "new payee"),))
    behavior = BehaviorResult(10, ())
    ml = MlResult(0.9996, "xgb_v3", available=True, calibrated_for_upi=False, evaluation=XGB_EVALUATION)
    out = aggregate_and_decide(quiet, rules, behavior, ml, cfg)
    expected = round(8 * 0.25 + 10 * 0.25 + 0.9996 * 100.0 * 0.40 + 0.0)
    assert out.components["rules"] == 2.0
    assert out.components["behavior"] == 2.5
    assert abs(out.components["ml"] - 39.984) < 1e-9
    assert out.components["security"] == 0.0
    assert out.risk_score == expected == 44
    assert out.decision == "REVIEW"
    reasons = " ".join(item.factor for item in out.risk_factors)
    assert "Uncalibrated PaySim" in reasons


def test_cutovers_use_canonical_0_100_score() -> None:
    cfg = RiskConfig()
    quiet = SecuritySignals(False, False, False, False, 0)
    empty = RuleResult(0, ())
    beh = BehaviorResult(0, ())
    allow = aggregate_and_decide(quiet, empty, beh, MlResult(0.02, "xgb_v3"), cfg)
    review = aggregate_and_decide(quiet, empty, beh, MlResult(0.90, "xgb_v3"), cfg)
    block = aggregate_and_decide(
        quiet,
        RuleResult(80, (TriggeredRule("HIGH_VELOCITY", "HIGH", 80, "burst"),)),
        BehaviorResult(80, ()),
        MlResult(0.90, "xgb_v3"),
        cfg,
    )
    assert allow.risk_score <= cfg.allow_max
    assert allow.decision == "ALLOW"
    assert cfg.allow_max < review.risk_score <= cfg.review_max
    assert review.decision == "REVIEW"
    assert block.risk_score > cfg.review_max
    assert block.decision == "BLOCK"


def test_persisted_result_keeps_components_explanations_and_action(tmp_path: Path) -> None:
    store = RiskStore(tmp_path / "persist.db")
    result = evaluate_transaction(
        {
            "transaction_id": "diag-persist",
            "user_id": "USR_PERSIST",
            "amount": 1000,
            "merchant_id": "sneha.roy@okaxis",
            "merchant_category": "p2p",
            "timestamp": NOW.isoformat(),
            "device_id": "dev-1",
            "latitude": 12.9716,
            "longitude": 77.5946,
        },
        store=store,
        config=RiskConfig(),
    )
    saved = store.get_result("diag-persist")
    assert saved is not None
    assert saved["components"] == result["components"]
    assert set(saved["components"]) == {"rules", "behavior", "ml", "security"}
    assert saved["ml"]["calibrated_for_upi"] is False
    assert saved["ml"]["evaluation"] == XGB_EVALUATION
    assert "ML_UNCALIBRATED_PAYSIM" in saved["reason_codes"]
    assert saved["action"] == result["action"]
    assert saved["risk_factors"] == result["risk_factors"]
    assert saved["decision"] == result["decision"]
    assert saved["risk_score"] == result["risk_score"]


def test_autoencoder_does_not_enter_canonical_components(tmp_path: Path) -> None:
    store = RiskStore(tmp_path / "ae.db")
    result = evaluate_transaction(
        {
            "transaction_id": "diag-ae",
            "user_id": "USR_AE",
            "amount": 240,
            "merchant_id": "kirana@oksbi",
            "timestamp": NOW.isoformat(),
        },
        store=store,
        config=RiskConfig(),
    )
    assert set(result["components"]) == {"rules", "behavior", "ml", "security"}
    assert "ae" not in result["components"]
    assert "P_ae" not in result["components"]
    note = result["experimental"]["note"]
    assert "not blended" in note


def test_demo_batch_saturation_is_flagged_uncalibrated_not_silently_trusted() -> None:
    reset_model()
    try:
        hot = 0
        rows = [
            _txn(200, "kirana@oksbi"),
            _txn(1000, "sneha.roy@okaxis"),
            _txn(48000, "stranger@oksbi"),
            _txn(240, "kirana@oksbi", gps=False, device=""),
        ]
        for txn in rows:
            ml = infer_fraud(txn, [], None)
            assert ml.available is True
            if ml.fraud_probability >= 0.9:
                hot += 1
        status = model_status()
        assert status["calibrated_for_upi"] is False
        if hot:
            assert status["evaluation"] == "synthetic_paysim"
            assert "UPI-calibrated" not in (status["note"] or "")
    finally:
        reset_model()
