"""Phase 2: shared feature list, no invented GPS, honest metrics."""

from datetime import datetime, timezone
from pathlib import Path

from risk.config import RiskConfig
from risk.ml_layer import LIVE_FEATURE_NAMES, engineer_features
from risk.normalize import normalize_transaction
from risk.pipeline import evaluate_transaction
from risk.store import RiskStore


def test_train_and_infer_share_feature_names() -> None:
    from detection.scoring_engine import FEATURE_VECTOR_NAMES

    assert LIVE_FEATURE_NAMES[: len(FEATURE_VECTOR_NAMES)] == FEATURE_VECTOR_NAMES
    assert "hour_of_day" in LIVE_FEATURE_NAMES
    assert "amount_to_median" in LIVE_FEATURE_NAMES
    assert "velocity_1m" in LIVE_FEATURE_NAMES
    assert "is_full_drain" not in LIVE_FEATURE_NAMES
    assert "is_cash_out" not in LIVE_FEATURE_NAMES


def test_paysim_without_gps_is_unknown_location() -> None:
    txn = normalize_transaction(
        {
            "transaction_id": "ps_1",
            "user_id": "C123",
            "amount": 9000,
            "payee_vpa": "M1@ps",
            "timestamp": datetime(2017, 1, 2, tzinfo=timezone.utc),
            "payment_type": "CASH_OUT",
            "origin_balance": 9000,
            "new_origin_balance": 0,
        }
    )
    vector = engineer_features(txn, [], home=None)
    assert list(vector) == list(LIVE_FEATURE_NAMES)
    assert vector["missing_location"] == 1.0
    assert vector["dist_from_home"] == 0.0
    assert vector["dist_from_last"] == 0.0
    assert vector["impossible_travel"] == 0.0
    assert vector["location_reliable"] == 0.0
    assert vector["amount_spike"] == 0.0
    assert vector["history_size"] == 0.0


def test_electronics_still_not_automatic_fraud(tmp_path: Path) -> None:
    store = RiskStore(tmp_path / "elec.db")
    result = evaluate_transaction(
        {
            "transaction_id": "TXN_ELEC_P2",
            "user_id": "USR_ELEC_P2",
            "amount": 1800,
            "merchant_id": "croma@oksbi",
            "merchant_category": "electronics",
            "timestamp": datetime(2026, 9, 28, 11, 0, tzinfo=timezone.utc).isoformat(),
            "latitude": 12.9716,
            "longitude": 77.5946,
        },
        store=store,
        config=RiskConfig(),
    )
    names = {item["rule"] for item in result["rules"]["triggered_rules"]}
    assert "HIGH_RISK_MERCHANT" not in names


def test_geo_features_are_not_the_model() -> None:
    import joblib

    path = Path(__file__).resolve().parents[2] / "ml" / "models" / "xgboost_model.pkl"
    if not path.exists():
        return
    loaded = joblib.load(path)
    model = loaded["model"] if isinstance(loaded, dict) and "model" in loaded else loaded
    names = list(LIVE_FEATURE_NAMES)
    n_in = int(getattr(model, "n_features_in_", len(names)))
    names = names[:n_in]
    share = float(
        sum(
            float(imp)
            for name, imp in zip(names, model.feature_importances_)
            if name in {"dist_from_home", "dist_from_last", "impossible_travel"}
        )
    )
    assert share < 0.5


def test_metrics_file_is_honest() -> None:
    path = Path(__file__).resolve().parents[2] / "ml" / "models" / "xgboost_metrics.json"
    if not path.exists():
        return
    import json

    metrics = json.loads(path.read_text(encoding="utf-8"))
    assert metrics.get("geo_leak") is False
    assert abs(float(metrics["roc_auc"]) - 1.0) > 1e-6
    assert metrics.get("evaluation") == "synthetic_paysim"
    assert metrics.get("calibrated_for_upi") is False
    assert metrics.get("feature_names") == list(LIVE_FEATURE_NAMES)
    assert "is_full_drain" not in metrics["feature_names"]
    assert float(metrics.get("max_abs_label_corr") or 0) < 0.9
    assert metrics.get("limitations")
