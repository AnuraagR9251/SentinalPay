"""Controlled XGBoost comparisons. Never writes the committed xgb_v3 pickle."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd
from xgboost import XGBClassifier

from ml.xgb_eval import (
    THRESHOLD_SELECTION,
    best_threshold,
    calibrate_scores,
    constant_fraud_metrics,
    pack_clf_metrics,
    ranking_intervals,
    recall_at_fpr_from_val,
    split_report,
    temporal_subwindows,
)
from risk.ml_layer import LIVE_FEATURE_NAMES

RANDOM_SEED = 7102
HYPERPARAMS = {
    "n_estimators": 180,
    "max_depth": 5,
    "learning_rate": 0.08,
    "subsample": 0.85,
    "colsample_bytree": 0.85,
    "objective": "binary:logistic",
    "eval_metric": "aucpr",
    "tree_method": "hist",
    "n_jobs": 4,
    "random_state": RANDOM_SEED,
}

# PaySim step-hours are not UPI circadian time, so cyclic hour is not justified there.
CYCLIC_TIME_JUSTIFIED = False


def smote_train(x_train: np.ndarray, y_train: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    from imblearn.over_sampling import SMOTE

    counts = np.bincount(y_train.astype(int), minlength=2)
    minority = int(counts.min())
    if minority < 2:
        return x_train, y_train
    sampler = SMOTE(random_state=RANDOM_SEED, k_neighbors=min(5, minority - 1))
    return sampler.fit_resample(x_train, y_train)


def _xy(frame: pd.DataFrame, cols: Sequence[str]) -> tuple[np.ndarray, np.ndarray]:
    return frame[list(cols)].to_numpy(dtype=np.float32), frame["_y"].to_numpy(dtype=np.int32)


def _with_cyclic(frame: pd.DataFrame, cols: Sequence[str]) -> tuple[pd.DataFrame, list[str]]:
    from ml.xgb_eval import cyclic_hour_columns

    if "hour_of_day" not in frame.columns:
        return frame, list(cols)
    out = frame.copy()
    sin, cos = cyclic_hour_columns(out["hour_of_day"].to_numpy())
    out["hour_sin"] = sin
    out["hour_cos"] = cos
    names = [c for c in cols if c != "hour_of_day"] + ["hour_sin", "hour_cos"]
    return out, names


def fit_xgb(
    x: np.ndarray,
    y: np.ndarray,
    *,
    scale_pos_weight: float = 1.0,
    n_estimators: int | None = None,
) -> XGBClassifier:
    params = dict(HYPERPARAMS)
    if n_estimators is not None:
        params["n_estimators"] = n_estimators
    model = XGBClassifier(**params, scale_pos_weight=float(scale_pos_weight))
    model.fit(x, y)
    return model


def design_e(val_metrics: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Pick train-time changes using validation only. Test stays unused."""
    a = val_metrics["A"]
    b = val_metrics["B"]
    d = val_metrics["D"]
    drop_hour = float(b["recall_at_5pct_fpr"]["recall"]) >= float(a["recall_at_5pct_fpr"]["recall"])
    no_smote = float(d["brier"]) <= float(a["brier"]) and float(d["recall_at_5pct_fpr"]["recall"]) >= (
        float(a["recall_at_5pct_fpr"]["recall"]) - 0.02
    )
    features = [name for name in LIVE_FEATURE_NAMES if not (drop_hour and name == "hour_of_day")]
    return {
        "drop_hour_of_day": drop_hour,
        "use_smote": not no_smote,
        "cyclic": False,
        "cyclic_justified": CYCLIC_TIME_JUSTIFIED,
        "feature_names": features,
        "note": "cyclic hour skipped: PaySim step-hour is not wall-clock UPI time",
    }


def _eval_pack(
    model: XGBClassifier, frame: pd.DataFrame, cols: Sequence[str], thresh: float
) -> tuple[dict[str, Any], np.ndarray, np.ndarray]:
    x, y = _xy(frame, cols)
    scores = model.predict_proba(x)[:, 1]
    packed = pack_clf_metrics(y, scores, thresh)
    packed["split"] = split_report("eval", frame)
    return packed, scores, y


def _window_packs(
    model: XGBClassifier, test_df: pd.DataFrame, cols: Sequence[str], thresh: float
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, window in enumerate(temporal_subwindows(test_df, 3)):
        packed, _, _ = _eval_pack(model, window, cols, thresh)
        packed["window"] = i
        packed["split"] = split_report(f"test_w{i}", window)
        out.append(packed)
    return out


def _decorate_test(
    test_pack: dict[str, Any],
    y_val: np.ndarray,
    p_val: np.ndarray,
    y_test: np.ndarray,
    p_test: np.ndarray,
) -> dict[str, Any]:
    test_pack["recall_at_1pct_fpr_val_selected"] = recall_at_fpr_from_val(y_val, p_val, y_test, p_test, 0.01)
    test_pack["recall_at_5pct_fpr_val_selected"] = recall_at_fpr_from_val(y_val, p_val, y_test, p_test, 0.05)
    test_pack["intervals"] = ranking_intervals(y_test, p_test)
    test_pack["threshold_selection"] = THRESHOLD_SELECTION
    return test_pack


def run_candidates(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    test_df: pd.DataFrame,
    *,
    n_estimators: int | None = None,
) -> dict[str, Any]:
    """Same rows for every candidate. Thresholds and calibration use val only."""
    specs = {
        "A": {"cols": list(LIVE_FEATURE_NAMES), "smote": True, "cyclic": False},
        "B": {"cols": [c for c in LIVE_FEATURE_NAMES if c != "hour_of_day"], "smote": True, "cyclic": False},
        "C": {"cols": list(LIVE_FEATURE_NAMES), "smote": True, "cyclic": True},
        "D": {"cols": list(LIVE_FEATURE_NAMES), "smote": False, "cyclic": False},
    }
    results: dict[str, Any] = {}
    val_summary: dict[str, dict[str, Any]] = {}
    arrays: dict[str, dict[str, np.ndarray]] = {}

    for name, spec in specs.items():
        train_use, cols = (train_df, list(spec["cols"]))
        val_use, test_use = val_df, test_df
        if spec["cyclic"]:
            train_use, cols = _with_cyclic(train_df, spec["cols"])
            val_use, cols = _with_cyclic(val_df, spec["cols"])
            test_use, cols = _with_cyclic(test_df, spec["cols"])
        x_train, y_train = _xy(train_use, cols)
        x_val, y_val = _xy(val_use, cols)
        if spec["smote"]:
            x_fit, y_fit = smote_train(x_train, y_train)
            spw = 1.0
        else:
            x_fit, y_fit = x_train, y_train
            n_pos = max(int(np.sum(y_train == 1)), 1)
            n_neg = max(int(np.sum(y_train == 0)), 1)
            spw = n_neg / n_pos
        # Val/test must stay the original arrays — never resampled.
        assert x_val.shape[0] == len(val_df)
        model = fit_xgb(x_fit, y_fit, scale_pos_weight=spw, n_estimators=n_estimators)
        p_train = model.predict_proba(x_train)[:, 1]
        p_val = model.predict_proba(x_val)[:, 1]
        thresh = best_threshold(y_val, p_val)
        val_pack, _, _ = _eval_pack(model, val_use, cols, thresh)
        test_pack, p_test, y_test = _eval_pack(model, test_use, cols, thresh)
        _decorate_test(test_pack, y_val, p_val, y_test, p_test)
        p_cal = calibrate_scores(p_val, y_val, p_test, method="sigmoid")
        cal_pack = pack_clf_metrics(y_test, p_cal, best_threshold(y_val, calibrate_scores(p_val, y_val, p_val)))
        entry: dict[str, Any] = {
            "feature_names": cols,
            "hyperparams": {**HYPERPARAMS, "n_estimators": n_estimators or HYPERPARAMS["n_estimators"], "scale_pos_weight": spw},
            "smote": spec["smote"],
            "cyclic": spec["cyclic"],
            "cyclic_justified": CYCLIC_TIME_JUSTIFIED if spec["cyclic"] else None,
            "threshold_source": "validation_f1",
            "threshold": thresh,
            "val": val_pack,
            "test": test_pack,
            "test_calibrated_sigmoid_paysim": cal_pack,
            "calibrated_for_upi": False,
        }
        if name in {"A", "B"}:
            entry["test_windows"] = _window_packs(model, test_use, cols, thresh)
        results[name] = entry
        val_summary[name] = val_pack
        arrays[name] = {"train": p_train, "val": p_val, "test": p_test}

    e_design = design_e(val_summary)
    e_train, e_cols = train_df, list(e_design["feature_names"])
    e_val, e_test = val_df, test_df
    x_train, y_train = _xy(e_train, e_cols)
    if e_design["use_smote"]:
        x_fit, y_fit = smote_train(x_train, y_train)
        spw = 1.0
    else:
        x_fit, y_fit = x_train, y_train
        n_pos = max(int(np.sum(y_train == 1)), 1)
        spw = max(int(np.sum(y_train == 0)), 1) / n_pos
    model_e = fit_xgb(x_fit, y_fit, scale_pos_weight=spw, n_estimators=n_estimators)
    x_val, y_val = _xy(e_val, e_cols)
    p_train = model_e.predict_proba(x_train)[:, 1]
    p_val = model_e.predict_proba(x_val)[:, 1]
    thresh = best_threshold(y_val, p_val)
    val_pack, _, _ = _eval_pack(model_e, e_val, e_cols, thresh)
    test_pack, p_test, y_test = _eval_pack(model_e, e_test, e_cols, thresh)
    _decorate_test(test_pack, y_val, p_val, y_test, p_test)
    p_cal = calibrate_scores(p_val, y_val, p_test, method="sigmoid")
    cal_pack = pack_clf_metrics(y_test, p_cal, best_threshold(y_val, calibrate_scores(p_val, y_val, p_val)))
    results["E"] = {
        "feature_names": e_cols,
        "design": e_design,
        "hyperparams": {**HYPERPARAMS, "n_estimators": n_estimators or HYPERPARAMS["n_estimators"], "scale_pos_weight": spw},
        "smote": e_design["use_smote"],
        "threshold_source": "validation_f1",
        "threshold": thresh,
        "val": val_pack,
        "test": test_pack,
        "test_calibrated_sigmoid_paysim": cal_pack,
        "calibrated_for_upi": False,
        "replace_xgb_v3": False,
        "replace_reason": "PaySim-only comparison; no labeled UPI holdout",
    }
    arrays["E"] = {"train": p_train, "val": p_val, "test": p_test}
    y_test = test_df["_y"].to_numpy(dtype=np.int32)
    return {
        "evaluation": "synthetic_paysim_or_fixture",
        "seed": RANDOM_SEED,
        "n_train": int(len(train_df)),
        "n_val": int(len(val_df)),
        "n_test": int(len(test_df)),
        "splits": {
            "train": split_report("train", train_df),
            "val": split_report("val", val_df),
            "test": split_report("test", test_df),
        },
        "candidates": results,
        "baselines": {"constant_fraud": constant_fraud_metrics(y_test)},
        "threshold_selection": THRESHOLD_SELECTION,
        "calibrated_for_upi": False,
        "_arrays": arrays,
    }


def write_experiment_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {key: value for key, value in report.items() if not str(key).startswith("_")}
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
