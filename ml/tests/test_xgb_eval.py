"""Evaluation splits, leakage, and experiment plumbing — no PaySim CSV required."""

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from ml.train_xgboost import paysim_csv_available, train
from ml.xgb_eval import (
    anonymize_user,
    assert_temporal_order,
    attach_eval_ids,
    best_threshold,
    calibrate_scores,
    chronological_thirds,
    constant_features,
    constant_fraud_metrics,
    hour_of_day_analysis,
    pack_clf_metrics,
    prediction_table,
    recall_at_fpr_from_val,
    split_report,
    stable_row_id,
    temporal_subwindows,
    user_disjoint_thirds,
    write_prediction_table,
)
from ml.xgb_experiments import CYCLIC_TIME_JUSTIFIED, design_e, run_candidates, smote_train, write_experiment_report
from risk.ml_layer import LIVE_FEATURE_NAMES, engineer_features
from risk.normalize import normalize_transaction


def _frame(n: int = 40, users: int = 10) -> pd.DataFrame:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rng = np.random.default_rng(7102)
    rows = []
    for i in range(n):
        row = {name: float(rng.random()) for name in LIVE_FEATURE_NAMES}
        row["hour_of_day"] = (i % 24) / 23.0
        row["_y"] = int(i % 4 == 0)
        row["_ts"] = start + timedelta(hours=i)
        row["_user"] = f"u{i % users}"
        rows.append(row)
    return pd.DataFrame(rows)


def test_paysim_csv_missing_on_this_checkout() -> None:
    if paysim_csv_available():
        pytest.skip("PaySim CSV is present; missing-path test does not apply")
    with pytest.raises(FileNotFoundError, match="xgb_v3 was not overwritten"):
        train()


def test_user_disjoint_has_no_user_overlap() -> None:
    frame = _frame(60, users=12)
    train_df, val_df, test_df = user_disjoint_thirds(frame, seed=7102)
    sets = (
        set(train_df["_user"]),
        set(val_df["_user"]),
        set(test_df["_user"]),
    )
    assert not sets[0] & sets[1]
    assert not sets[0] & sets[2]
    assert not sets[1] & sets[2]
    assert len(train_df) + len(val_df) + len(test_df) == len(frame)


def test_temporal_order_rejects_shuffled_folds() -> None:
    train_df, val_df, test_df = chronological_thirds(_frame(20, users=10))
    assert_temporal_order(train_df, val_df, test_df)
    with pytest.raises(RuntimeError, match="temporal split leaked"):
        assert_temporal_order(test_df, val_df, train_df)


def test_threshold_uses_validation_labels_only() -> None:
    y_val = np.array([0, 0, 1, 1])
    p_val = np.array([0.1, 0.2, 0.8, 0.9])
    thresh = best_threshold(y_val, p_val)
    y_test = np.array([1, 1, 1, 1])
    p_test = np.array([0.01, 0.02, 0.03, 0.04])
    test_only = best_threshold(y_test, p_test)
    assert best_threshold(y_val, p_val) == thresh
    assert thresh != test_only
    packed = pack_clf_metrics(y_test, p_test, thresh)
    assert packed["threshold"] == thresh


def test_smote_does_not_resample_holdout() -> None:
    rng = np.random.default_rng(0)
    x_train = rng.random((20, 4))
    y_train = np.array([0] * 15 + [1] * 5)
    x_val = rng.random((8, 4))
    x_res, y_res = smote_train(x_train, y_train)
    assert x_val.shape == (8, 4)
    assert len(x_res) >= len(x_train)
    assert int(np.sum(y_res == 0)) == int(np.sum(y_res == 1))


def test_split_report_flags_unusual_prevalence() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    hot = pd.DataFrame({"_y": [1] * 18 + [0, 0], "_ts": [start] * 20})
    report = split_report("test", hot)
    assert report["n_fraud"] == 18
    assert report["unusual_prevalence"] is True


def test_constant_features_and_windows() -> None:
    frame = _frame(12, users=10)
    frame["vpn_proxy"] = 0.0
    assert "vpn_proxy" in constant_features(frame, list(LIVE_FEATURE_NAMES))
    windows = temporal_subwindows(frame, 3)
    assert len(windows) == 3
    assert sum(len(w) for w in windows) == 12


def test_calibration_is_paysim_not_upi() -> None:
    y = np.array([0, 0, 0, 1, 1, 1])
    p = np.array([0.1, 0.2, 0.3, 0.6, 0.7, 0.9])
    out = calibrate_scores(p, y, p, method="sigmoid")
    assert np.all(np.isfinite(out))
    assert np.all((out >= 0.0) & (out <= 1.0))
    assert CYCLIC_TIME_JUSTIFIED is False


def test_design_e_never_enables_unjustified_cyclic() -> None:
    dummy = {
        "recall_at_5pct_fpr": {"recall": 0.5},
        "brier": 0.2,
    }
    chosen = design_e({"A": dummy, "B": dummy, "D": dummy})
    assert chosen["cyclic"] is False
    assert chosen["cyclic_justified"] is False


def test_candidates_share_holdout_rows() -> None:
    frame = _frame(48, users=12)
    train_df, val_df, test_df = chronological_thirds(frame)
    report = run_candidates(train_df, val_df, test_df, n_estimators=8)
    assert report["calibrated_for_upi"] is False
    assert report["n_test"] == len(test_df)
    for name in ("A", "B", "C", "D", "E"):
        cand = report["candidates"][name]
        assert cand["test"]["n"] == len(test_df)
        assert cand["calibrated_for_upi"] is False
        assert cand["threshold_source"] == "validation_f1"
        assert "recall_at_1pct_fpr_val_selected" in cand["test"]
        assert name in report["_arrays"]
        assert report["_arrays"][name]["test"].shape[0] == len(test_df)
    assert report["candidates"]["C"]["cyclic_justified"] is False
    assert report["candidates"]["E"]["replace_xgb_v3"] is False
    assert "test_windows" in report["candidates"]["A"]
    assert "test_windows" in report["candidates"]["B"]
    cf = report["baselines"]["constant_fraud"]
    p = test_df["_y"].mean()
    assert cf["precision"] == pytest.approx(p)
    assert cf["f1_closed_form"] == pytest.approx(2 * p / (1 + p))


def test_stable_ids_are_deterministic_and_anonymized() -> None:
    ts = datetime(2017, 1, 24, 5, tzinfo=timezone.utc)
    assert stable_row_id("C123", ts, 0) == stable_row_id("C123", ts, 0)
    assert stable_row_id("C123", ts, 0) != stable_row_id("C123", ts, 1)
    assert "C123" not in stable_row_id("C123", ts, 0)
    assert "C123" not in anonymize_user("C123")
    frame = attach_eval_ids(_frame(12, users=4))
    assert frame["_row_id"].nunique() == 12
    assert set(frame["_user_anon"]) == {anonymize_user(u) for u in frame["_user"]}


def test_constant_fraud_f1_matches_prevalence_formula() -> None:
    y = np.array([1] * 2063 + [0] * 83)
    packed = constant_fraud_metrics(y)
    p = 2063 / 2146
    assert packed["precision"] == pytest.approx(p)
    assert packed["recall"] == 1.0
    assert packed["f1"] == pytest.approx(2 * p / (1 + p))
    assert packed["f1_closed_form"] == pytest.approx(0.980280351627465)


def test_prediction_table_omits_raw_user(tmp_path) -> None:
    frame = attach_eval_ids(_frame(12, users=4))
    scores = {"A": {"test": np.linspace(0.1, 0.9, 12)}}
    table = prediction_table({"test": frame}, scores)
    assert "_user" not in table.columns
    assert "C123" not in table.to_csv(index=False)
    path = tmp_path / "pred.csv"
    write_prediction_table(path, table)
    leaked = table.copy()
    leaked["_user"] = frame["_user"].to_numpy()
    with pytest.raises(RuntimeError, match="raw identity"):
        write_prediction_table(tmp_path / "bad.csv", leaked)


def test_val_selected_fpr_threshold_is_frozen() -> None:
    y_val = np.array([0, 0, 0, 0, 1, 1, 1, 1])
    p_val = np.array([0.1, 0.2, 0.3, 0.85, 0.4, 0.5, 0.6, 0.9])
    y_test = np.array([0, 0, 1, 1])
    p_test = np.array([0.05, 0.99, 0.2, 0.95])
    applied = recall_at_fpr_from_val(y_val, p_val, y_test, p_test, 0.25)
    assert applied["selection"] == "validation_max_recall_at_fpr"
    assert applied["threshold"] == applied["val_threshold"]


def test_hour_of_day_matches_timestamp_clock() -> None:
    frame = _frame(24, users=8)
    report = hour_of_day_analysis({"test": frame})
    assert report["calibrated_for_upi"] is False
    assert report["splits"]["test"]["max_abs_hour_of_day_vs_clock_over_23"] == pytest.approx(0.0)


def test_experiment_json_strips_score_arrays(tmp_path) -> None:
    frame = _frame(48, users=12)
    train_df, val_df, test_df = chronological_thirds(frame)
    report = run_candidates(train_df, val_df, test_df, n_estimators=8)
    path = tmp_path / "candidates.json"
    write_experiment_report(report, path)
    text = path.read_text(encoding="utf-8")
    assert "_arrays" not in text
    assert "constant_fraud" in text


def test_causal_history_ignores_future_payee_and_amount() -> None:
    ts0 = datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc)
    past = normalize_transaction(
        {
            "transaction_id": "p0",
            "user_id": "USR_C",
            "amount": 200,
            "merchant_id": "kirana@oksbi",
            "timestamp": ts0.isoformat(),
            "device_id": "dev-1",
        }
    )
    now = normalize_transaction(
        {
            "transaction_id": "p1",
            "user_id": "USR_C",
            "amount": 220,
            "merchant_id": "kirana@oksbi",
            "timestamp": (ts0 + timedelta(minutes=2)).isoformat(),
            "device_id": "dev-1",
        }
    )
    future = normalize_transaction(
        {
            "transaction_id": "p2",
            "user_id": "USR_C",
            "amount": 48000,
            "merchant_id": "stranger@oksbi",
            "timestamp": (ts0 + timedelta(minutes=5)).isoformat(),
            "device_id": "dev-9",
        }
    )

    def row(txn):
        return {
            "amount": txn.amount,
            "timestamp": txn.timestamp,
            "merchant_id": txn.merchant_id,
            "device_id": txn.device_id,
        }

    leaked = engineer_features(now, [row(past), row(future)], home=None)
    clean = engineer_features(now, [row(past)], home=None)
    assert leaked["amount_spike"] == clean["amount_spike"]
    assert leaked["recipient_prior_count"] == clean["recipient_prior_count"]
    assert leaked["new_device"] == clean["new_device"]
    assert list(leaked) == list(LIVE_FEATURE_NAMES)
