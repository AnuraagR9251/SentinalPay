"""Train a binary XGBoost fraud classifier on behavioural + PaySim signals.

Usage (from repo root):

    python ml/train_xgboost.py
    py -3 ml/train_xgboost.py

PaySim has no GPS. Drain/CASH_OUT flags are not ML features (simulator leak).
Chronological 60/20/20 split. SMOTE is fit on the training fold only.
UPI statement rows are unlabeled and are not used for metrics.
Train and live infer share risk.ml_layer.LIVE_FEATURE_NAMES.
Evaluation is synthetic-data only until labeled UPI history exists.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import joblib
import numpy as np
import pandas as pd
from imblearn.over_sampling import SMOTE
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from ml.xgb_eval import (  # noqa: E402
    THRESHOLD_SELECTION,
    assert_temporal_order,
    attach_eval_ids,
    best_threshold,
    brier_and_reliability,
    chronological_split,
    chronological_thirds,
    constant_features,
    constant_fraud_metrics,
    feature_export_table,
    hour_of_day_analysis,
    leakage_correlations,
    pack_clf_metrics,
    prediction_table,
    recall_at_fpr,
    review_operating_point,
    split_report,
    temporal_subwindows,
    user_disjoint_thirds,
    write_prediction_table,
)
from risk.ml_layer import LIVE_FEATURE_NAMES, engineer_features  # noqa: E402
from risk.normalize import NormalizationError, normalize_transaction  # noqa: E402

logging.basicConfig(level=os.getenv("SENTINALPAY_LOG_LEVEL", "INFO"))
logger = logging.getLogger("sentinalpay.ml.xgb")

DATASET_DIR = REPO_ROOT / "dataset"
PAYSIM_PATH = DATASET_DIR / "PS_20174392719_1491204439457_log.csv"
UPI_PATH = DATASET_DIR / "upi_transactions_2025.csv"
MODEL_DIR = REPO_ROOT / "ml" / "models"
MODEL_PATH = MODEL_DIR / "xgboost_model.pkl"
METRICS_PATH = MODEL_DIR / "xgboost_metrics.json"
ARTIFACT_DIR = REPO_ROOT / "ml" / "artifacts" / "xgb_experiments"
EVAL_REPRO_DIR = ARTIFACT_DIR / "eval_repro"

CHUNK_SIZE = 250_000
LEGIT_USER_CAP = 2_500
LEGIT_SEQ_CAP = 16
RANDOM_SEED = 7102
PAYSIM_EPOCH = datetime(2017, 1, 1, tzinfo=timezone.utc)


def _as_history_row(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "transaction_id": raw.get("transaction_id") or "hist",
        "user_id": raw.get("user_id") or "unknown",
        "amount": float(raw["amount"]),
        "merchant_id": raw.get("merchant_id") or raw.get("payee_vpa"),
        "timestamp": raw["timestamp"],
        "latitude": raw.get("latitude", raw.get("lat")),
        "longitude": raw.get("longitude", raw.get("lon")),
        "device_id": raw.get("device_id"),
        "ip_address": raw.get("ip_address"),
    }


def _vector_row(raw: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any] | None:
    try:
        txn = normalize_transaction(raw)
    except NormalizationError:
        return None
    vector = engineer_features(txn, history, home=None)
    return {name: float(vector.get(name, 0.0)) for name in LIVE_FEATURE_NAMES}


def _walk_sequence(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events = sorted(events, key=lambda item: item["txn"]["timestamp"])
    history: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for event in events:
        vector = _vector_row(event["txn"], history)
        if vector is None:
            continue
        rows.append(
            {
                **vector,
                "_y": event["y"],
                "_ts": event["txn"]["timestamp"],
                "_user": event["txn"].get("user_id") or "unknown",
                "_seq": len(history),
            }
        )
        history.append(_as_history_row(event["txn"]))
    return rows


def _collect_paysim_users() -> tuple[set[str], set[str]]:
    if not PAYSIM_PATH.exists():
        raise FileNotFoundError(f"PaySim CSV not found at {PAYSIM_PATH}")
    fraud_users: set[str] = set()
    legit_res: list[str] = []
    seen_legit = 0
    seen_ids: set[str] = set()
    rng = np.random.default_rng(RANDOM_SEED)
    for chunk in pd.read_csv(PAYSIM_PATH, usecols=["nameOrig", "isFraud"], chunksize=CHUNK_SIZE):
        fraud_users.update(chunk.loc[chunk["isFraud"] == 1, "nameOrig"].astype(str))
        for uid in chunk.loc[chunk["isFraud"] == 0, "nameOrig"].astype(str).unique():
            if uid in seen_ids:
                continue
            seen_ids.add(uid)
            seen_legit += 1
            if len(legit_res) < LEGIT_USER_CAP:
                legit_res.append(uid)
            else:
                j = int(rng.integers(0, seen_legit))
                if j < LEGIT_USER_CAP:
                    legit_res[j] = uid
    legit_users = set(legit_res) - fraud_users
    logger.info("paysim fraud users=%s legit users=%s", len(fraud_users), len(legit_users))
    return fraud_users, legit_users


def _load_paysim_sequences() -> dict[str, list[dict[str, Any]]]:
    fraud_users, legit_users = _collect_paysim_users()
    wanted = fraud_users | legit_users
    sequences: dict[str, list[dict[str, Any]]] = defaultdict(list)
    usecols = ["step", "type", "amount", "nameOrig", "nameDest", "oldbalanceOrg", "newbalanceOrig", "isFraud"]

    for chunk in pd.read_csv(PAYSIM_PATH, usecols=usecols, chunksize=CHUNK_SIZE):
        orig = chunk["nameOrig"].astype(str)
        mask = orig.isin(wanted)
        if not mask.any():
            continue
        sub = chunk.loc[mask]
        for rec in sub.itertuples(index=False):
            user_id = str(rec.nameOrig)
            amount = float(rec.amount)
            if amount <= 0:
                continue
            if user_id not in fraud_users and len(sequences[user_id]) >= LEGIT_SEQ_CAP:
                continue
            txn = {
                "transaction_id": (
                    f"ps_{hashlib.sha256(user_id.encode('utf-8')).hexdigest()[:8]}"
                    f"_{int(rec.step)}_{len(sequences[user_id])}"
                ),
                "user_id": user_id,
                "amount": amount,
                "payee_vpa": f"{rec.nameDest}@ps",
                "timestamp": PAYSIM_EPOCH + timedelta(hours=int(rec.step)),
                "payment_type": str(rec.type),
                "origin_balance": float(rec.oldbalanceOrg),
                "new_origin_balance": float(rec.newbalanceOrig),
            }
            sequences[user_id].append({"txn": txn, "y": 1 if int(rec.isFraud) else 0})
    logger.info("paysim sequences=%s", len(sequences))
    return sequences


def _load_upi_sequence() -> list[dict[str, Any]]:
    if not UPI_PATH.exists():
        logger.warning("UPI CSV missing — training on PaySim only")
        return []
    frame = pd.read_csv(UPI_PATH)
    events: list[dict[str, Any]] = []
    for idx, row in frame.iterrows():
        amount = float(row["Amount"])
        if amount <= 0:
            continue
        try:
            ts = datetime.fromisoformat(f"{row['Date']}T{row['Time']}").replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        purpose = str(row.get("Type") or row.get("Category") or "merchant_payment")
        txn = {
            "transaction_id": str(row["Transaction_ID"]),
            "user_id": "upi_statement_2025",
            "amount": amount,
            "payee_vpa": f"merchant_{int(idx) % 40}@upi",
            "timestamp": ts,
            "payment_type": purpose,
        }
        events.append({"txn": txn, "y": 0})
    logger.info("upi events=%s", len(events))
    return events


def build_feature_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    paysim_rows: list[dict[str, Any]] = []
    for events in _load_paysim_sequences().values():
        paysim_rows.extend(_walk_sequence(events))
    paysim = pd.DataFrame(paysim_rows)
    if paysim.empty:
        raise RuntimeError("no PaySim training rows — check dataset/ CSVs")

    upi_events = _load_upi_sequence()
    upi = pd.DataFrame(_walk_sequence(upi_events)) if upi_events else pd.DataFrame()
    logger.info(
        "feature rows paysim=%s fraud=%s upi=%s",
        len(paysim),
        int(paysim["_y"].sum()),
        len(upi),
    )
    return paysim, upi


def _leakage_correlations(frame: pd.DataFrame, cols: list[str]) -> dict[str, float]:
    return leakage_correlations(frame, cols)


def _rule_scores(frame: pd.DataFrame) -> np.ndarray:
    spike = frame["amount_spike"].to_numpy(dtype=np.float64) if "amount_spike" in frame else np.zeros(len(frame))
    vel = frame["velocity_5m"].to_numpy(dtype=np.float64) if "velocity_5m" in frame else np.zeros(len(frame))
    new_payee = frame["new_payee"].to_numpy(dtype=np.float64) if "new_payee" in frame else np.zeros(len(frame))
    return np.clip(0.4 * spike + 0.3 * vel + 0.3 * new_payee, 0.0, 1.0)


def _fit_logreg(x_train: np.ndarray, y_train: np.ndarray, x_out: np.ndarray) -> np.ndarray:
    scaler = StandardScaler()
    x_tr = scaler.fit_transform(x_train)
    clf = LogisticRegression(max_iter=400, class_weight="balanced", random_state=RANDOM_SEED)
    clf.fit(x_tr, y_train)
    return clf.predict_proba(scaler.transform(x_out))[:, 1]


def _best_threshold(y_true: np.ndarray, scores: np.ndarray) -> float:
    return best_threshold(y_true, scores)


def _pack_clf_metrics(y_true: np.ndarray, scores: np.ndarray, thresh: float) -> dict[str, Any]:
    return pack_clf_metrics(y_true, scores, thresh)


def _smote_train(x_train: np.ndarray, y_train: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    counts = np.bincount(y_train.astype(int), minlength=2)
    minority = int(counts.min())
    if minority < 2:
        logger.warning("SMOTE skipped — minority class has %s rows", minority)
        return x_train, y_train
    k_neighbors = min(5, minority - 1)
    sampler = SMOTE(random_state=RANDOM_SEED, k_neighbors=k_neighbors)
    return sampler.fit_resample(x_train, y_train)


def paysim_csv_available() -> bool:
    return PAYSIM_PATH.is_file()


def _card_delta(xgb_metrics: dict[str, Any]) -> dict[str, Any]:
    if not METRICS_PATH.is_file():
        return {"committed_card_present": False}
    card = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
    keys = ("roc_auc", "average_precision", "precision", "recall", "f1", "threshold")
    deltas = {key: abs(float(xgb_metrics[key]) - float(card[key])) for key in keys if key in card}
    return {
        "committed_card_present": True,
        "committed_model_version": card.get("model_version", "xgb_v3"),
        "deltas": deltas,
        "close_1e9": all(val <= 1e-9 for val in deltas.values()),
        "close_1e6": all(val <= 1e-6 for val in deltas.values()),
        "note": "18:27 artifacts did not store row IDs; this is metric-level closeness only",
    }


def _write_eval_repro(
    *,
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    test_df: pd.DataFrame,
    experiments: dict[str, Any],
    user_experiments: dict[str, Any] | None,
    user_frames: dict[str, pd.DataFrame] | None,
    hour: dict[str, Any],
    manifest: dict[str, Any],
    rule_test: np.ndarray,
    lr_test: np.ndarray,
) -> None:
    EVAL_REPRO_DIR.mkdir(parents=True, exist_ok=True)
    from ml.xgb_experiments import write_experiment_report

    write_experiment_report(experiments, EVAL_REPRO_DIR / "candidates.json")
    frames = {"train": train_df, "val": val_df, "test": test_df}
    arrays = experiments.get("_arrays") or {}
    if arrays:
        write_prediction_table(EVAL_REPRO_DIR / "predictions.csv", prediction_table(frames, arrays))
    write_prediction_table(
        EVAL_REPRO_DIR / "baselines_test.csv",
        prediction_table(
            {"test": test_df},
            {
                "rules": {"test": rule_test},
                "logreg": {"test": lr_test},
                "constant_fraud": {"test": np.ones(len(test_df), dtype=np.float64)},
            },
        ),
    )
    feature_export_table(frames, list(LIVE_FEATURE_NAMES)).to_csv(
        EVAL_REPRO_DIR / "feature_rows.csv.gz", index=False, compression="gzip"
    )
    if user_experiments is not None and user_frames is not None:
        write_experiment_report(user_experiments, EVAL_REPRO_DIR / "user_disjoint_candidates.json")
        u_arrays = user_experiments.get("_arrays") or {}
        if u_arrays:
            u_split = {"train": user_frames["user_train"], "val": user_frames["user_val"], "test": user_frames["user_test"]}
            write_prediction_table(
                EVAL_REPRO_DIR / "predictions_user_disjoint.csv",
                prediction_table(u_split, u_arrays),
            )
    (EVAL_REPRO_DIR / "hour_of_day.json").write_text(json.dumps(hour, indent=2, default=str), encoding="utf-8")
    (EVAL_REPRO_DIR / "split_manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")


def train(*, promote: bool | None = None) -> dict[str, Any]:
    if not paysim_csv_available():
        raise FileNotFoundError(
            f"PaySim CSV not found at {PAYSIM_PATH}. "
            "Comparisons were not executed. Live xgb_v3 was not overwritten."
        )
    paysim, _upi = build_feature_frames()
    paysim = attach_eval_ids(paysim)
    # UPI statement file has no fraud labels — keep it out of scored evaluation.
    train_df, val_df, test_df = chronological_thirds(paysim)
    assert_temporal_order(train_df, val_df, test_df)
    feature_cols = list(LIVE_FEATURE_NAMES)
    leaks = _leakage_correlations(train_df, feature_cols)
    hot = {name: corr for name, corr in leaks.items() if abs(corr) >= 0.9}
    if hot:
        logger.warning("high label correlation (possible leak): %s", hot)
    dead = constant_features(train_df, feature_cols)

    x_train = train_df[feature_cols].to_numpy(dtype=np.float32)
    y_train = train_df["_y"].to_numpy(dtype=np.int32)
    x_val = val_df[feature_cols].to_numpy(dtype=np.float32)
    y_val = val_df["_y"].to_numpy(dtype=np.int32)
    x_test = test_df[feature_cols].to_numpy(dtype=np.float32)
    y_test = test_df["_y"].to_numpy(dtype=np.int32)
    val_n, test_n = len(y_val), len(y_test)

    logger.info(
        "split train=%s val=%s test=%s train_fraud=%s val_fraud=%s test_fraud=%s",
        len(y_train),
        len(y_val),
        len(y_test),
        int(y_train.sum()),
        int(y_val.sum()),
        int(y_test.sum()),
    )

    x_res, y_res = _smote_train(x_train, y_train)
    if len(y_val) != val_n or len(y_test) != test_n:
        raise RuntimeError("SMOTE must not change val/test row counts")
    logger.info("after SMOTE train=%s fraud=%s", len(y_res), int(y_res.sum()))

    model = XGBClassifier(
        n_estimators=180,
        max_depth=5,
        learning_rate=0.08,
        subsample=0.85,
        colsample_bytree=0.85,
        objective="binary:logistic",
        eval_metric="aucpr",
        tree_method="hist",
        n_jobs=4,
        random_state=RANDOM_SEED,
    )
    model.fit(x_res, y_res)

    xgb_val = model.predict_proba(x_val)[:, 1]
    thresh = _best_threshold(y_val, xgb_val)
    xgb_test = model.predict_proba(x_test)[:, 1]
    lr_test = _fit_logreg(x_train, y_train, x_test)
    rule_test = _rule_scores(test_df)
    xgb_metrics = _pack_clf_metrics(y_test, xgb_test, thresh)
    xgb_metrics["calibration_val"] = brier_and_reliability(y_val, xgb_val)
    lr_metrics = _pack_clf_metrics(y_test, lr_test, _best_threshold(y_val, _fit_logreg(x_train, y_train, x_val)))
    rule_metrics = _pack_clf_metrics(y_test, rule_test, _best_threshold(y_val, _rule_scores(val_df)))

    windows = []
    for i, window in enumerate(temporal_subwindows(test_df, 3)):
        p = model.predict_proba(window[feature_cols].to_numpy(dtype=np.float32))[:, 1]
        windows.append({"window": i, **split_report(f"test_w{i}", window), **_pack_clf_metrics(window["_y"].to_numpy(dtype=np.int32), p, thresh)})

    from ml.xgb_experiments import run_candidates, write_experiment_report

    user_eval: dict[str, Any] | None = None
    user_experiments: dict[str, Any] | None = None
    user_frames: dict[str, pd.DataFrame] | None = None
    if "_user" in paysim.columns and paysim["_user"].nunique() >= 10:
        u_train, u_val, u_test = user_disjoint_thirds(paysim, seed=RANDOM_SEED)
        user_frames = {"user_train": u_train, "user_val": u_val, "user_test": u_test}
        user_experiments = run_candidates(u_train, u_val, u_test)
        user_a = user_experiments["candidates"]["A"]
        user_b = user_experiments["candidates"]["B"]
        user_eval = {
            "note": "unseen originators; not a temporal test",
            "splits": {
                "train": split_report("user_train", u_train),
                "val": split_report("user_val", u_val),
                "test": split_report("user_test", u_test),
            },
            "threshold": user_a["threshold"],
            "test": user_a["test"],
            "hour_ablation": {"A": user_a["test"], "B": user_b["test"]},
            "baselines": user_experiments.get("baselines"),
        }

    experiments = run_candidates(train_df, val_df, test_df)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    write_experiment_report(experiments, ARTIFACT_DIR / "candidates.json")

    metrics = {
        "evaluation": "synthetic_paysim",
        "split": "chronological_60_20_20",
        "splits": {
            "train": split_report("train", train_df),
            "val": split_report("val", val_df),
            "test": split_report("test", test_df),
        },
        "sampling": {
            "fraud_users": "all originators with isFraud=1",
            "legit_user_cap": LEGIT_USER_CAP,
            "legit_seq_cap": LEGIT_SEQ_CAP,
            "note": "legit users reservoir-sampled; legit sequences truncated; fraud sequences kept in full",
        },
        "constant_features_train": dead,
        "precision": xgb_metrics["precision"],
        "recall": xgb_metrics["recall"],
        "f1": xgb_metrics["f1"],
        "roc_auc": xgb_metrics["roc_auc"],
        "average_precision": xgb_metrics["average_precision"],
        "threshold": xgb_metrics["threshold"],
        "threshold_source": "validation_f1",
        "threshold_selection": THRESHOLD_SELECTION,
        "review": xgb_metrics["review"],
        "test_windows": windows,
        "user_disjoint": user_eval,
        "baselines": {
            "rules": rule_metrics,
            "logistic_regression": lr_metrics,
            "xgboost": xgb_metrics,
            "constant_fraud": constant_fraud_metrics(y_test),
        },
        "feature_names": list(LIVE_FEATURE_NAMES),
        "max_abs_label_corr": max((abs(v) for v in leaks.values()), default=0.0),
        "high_corr_features": hot,
        "geo_leak": False,
        "calibrated_for_upi": False,
        "model_version": "xgb_v3",
        "geo_feature_importance_share": float(
            sum(
                float(model.feature_importances_[i])
                for i, name in enumerate(LIVE_FEATURE_NAMES)
                if name in {"dist_from_home", "dist_from_last", "impossible_travel"}
            )
        )
        if hasattr(model, "feature_importances_")
        else None,
        "replace_xgb_v3": False,
        "limitations": [
            "Synthetic-data evaluation (PaySim). Not a real UPI fraud holdout.",
            "No labeled historical UPI set was available; statement CSV is unlabeled and unused for metrics.",
            "CASH_OUT / full-drain flags excluded from ML to avoid simulator label leakage.",
            "Thresholds tuned on a later chronological slice; newest slice is the test report.",
            "Experimental — not a certified fraud detector.",
            "PaySim fraud is time-clustered; the newest slice can be mostly fraud, so PR/review rates are not a real UPI false-positive rate.",
            "hour_of_day is PaySim step-hour/23, not UPI circadian risk; it can dominate gain as a time-cluster proxy.",
            "velocity_5m / velocity_1m are wall-clock windows; PaySim steps are hours, so short windows rarely contain more than one event.",
            "Device and GPS features are missing in PaySim and are constant or uninformative in training.",
            "Not production-ready: synthetic labels, no UPI ATO labels, calibration is experimental.",
            "calibrated_for_upi is false until a labeled UPI holdout exists.",
        ],
    }
    print("evaluation=synthetic_paysim split=60/20/20")
    print(f"xgb precision={xgb_metrics['precision']:.4f} recall={xgb_metrics['recall']:.4f} ap={xgb_metrics['average_precision']:.4f}")
    print(f"lr  precision={lr_metrics['precision']:.4f} recall={lr_metrics['recall']:.4f} ap={lr_metrics['average_precision']:.4f}")
    print(f"rules precision={rule_metrics['precision']:.4f} recall={rule_metrics['recall']:.4f} ap={rule_metrics['average_precision']:.4f}")
    print(f"review fraud_recall={xgb_metrics['review']['fraud_recall']:.4f} legit_review_rate={xgb_metrics['review']['legit_review_rate']:.4f}")

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_DIR / "temporal_metrics.json").write_text(json.dumps(metrics, indent=2, default=str), encoding="utf-8")
    joblib.dump(
        {"model": model, "feature_names": list(LIVE_FEATURE_NAMES), "version": "xgb_experiment", "calibrated_for_upi": False},
        ARTIFACT_DIR / "xgboost_experiment.pkl",
    )
    hour = hour_of_day_analysis(
        {"train": train_df, "val": val_df, "test": test_df},
        epoch=PAYSIM_EPOCH,
        windows_a=experiments["candidates"]["A"].get("test_windows"),
        windows_b=experiments["candidates"]["B"].get("test_windows"),
    )
    manifest = {
        "evaluation": "synthetic_paysim",
        "calibrated_for_upi": False,
        "replace_xgb_v3": False,
        "seed": RANDOM_SEED,
        "paysim_csv": str(PAYSIM_PATH.name),
        "paysim_bytes": PAYSIM_PATH.stat().st_size if PAYSIM_PATH.is_file() else None,
        "row_id": "sha256(user|timestamp_iso|seq)[:16]",
        "user_anon": "sha256('sentinalpay|'+user)[:16]",
        "sampling": metrics["sampling"],
        "splits": metrics["splits"],
        "threshold_selection": THRESHOLD_SELECTION,
        "xgb_v3_card_match": _card_delta(xgb_metrics),
        "prior_run_missing": [
            "per-row labels",
            "per-row scores",
            "row ids",
            "split membership file",
        ],
        "reconstructed_from": "PaySim CSV + seed 7102 + chronological_thirds; prior run did not persist row IDs",
        "live_model_untouched": True,
    }
    _write_eval_repro(
        train_df=train_df,
        val_df=val_df,
        test_df=test_df,
        experiments=experiments,
        user_experiments=user_experiments,
        user_frames=user_frames,
        hour=hour,
        manifest=manifest,
        rule_test=rule_test,
        lr_test=lr_test,
    )
    (EVAL_REPRO_DIR / "temporal_metrics.json").write_text(json.dumps(metrics, indent=2, default=str), encoding="utf-8")
    should_promote = os.getenv("SENTINALPAY_XGB_PROMOTE", "").strip().lower() in {"1", "true", "yes"} if promote is None else promote
    if should_promote:
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        joblib.dump({"model": model, "feature_names": list(LIVE_FEATURE_NAMES), "version": "xgb_v3"}, MODEL_PATH)
        METRICS_PATH.write_text(json.dumps(metrics, indent=2, default=str), encoding="utf-8")
        print(f"promoted model -> {MODEL_PATH}")
    else:
        print(f"wrote experiment artifacts -> {ARTIFACT_DIR} (xgb_v3 not overwritten)")
        print(f"wrote row-level eval artifacts -> {EVAL_REPRO_DIR}")
    return metrics


if __name__ == "__main__":
    try:
        train()
    except FileNotFoundError as exc:
        print(exc)
        raise SystemExit(2) from exc
