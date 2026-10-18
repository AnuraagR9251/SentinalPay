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

import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from imblearn.over_sampling import SMOTE
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    f1_score,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

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
        rows.append({**vector, "_y": event["y"], "_ts": event["txn"]["timestamp"]})
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
                "transaction_id": f"ps_{abs(hash(user_id)) % 10_000_000}_{int(rec.step)}_{len(sequences[user_id])}",
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


def chronological_split(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    ordered = frame.sort_values("_ts", kind="mergesort").reset_index(drop=True)
    cut = int(len(ordered) * 0.8)
    if cut < 1 or cut >= len(ordered):
        raise RuntimeError("not enough rows for an 80/20 chronological split")
    return ordered.iloc[:cut], ordered.iloc[cut:]


def chronological_thirds(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Earlier → train, next → tune, newest → final eval."""
    ordered = frame.sort_values("_ts", kind="mergesort").reset_index(drop=True)
    n = len(ordered)
    a, b = int(n * 0.6), int(n * 0.8)
    if a < 1 or b <= a or b >= n:
        raise RuntimeError("not enough rows for a 60/20/20 chronological split")
    return ordered.iloc[:a], ordered.iloc[a:b], ordered.iloc[b:]


def _leakage_correlations(frame: pd.DataFrame, cols: list[str]) -> dict[str, float]:
    y = frame["_y"].to_numpy(dtype=np.float64)
    out: dict[str, float] = {}
    for col in cols:
        series = frame[col].to_numpy(dtype=np.float64)
        if float(np.std(series)) < 1e-12 or len(np.unique(y)) < 2:
            continue
        out[col] = float(np.corrcoef(series, y)[0, 1])
    return out


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
    precision, recall, thresholds = precision_recall_curve(y_true, scores)
    if thresholds.size == 0:
        return 0.5
    f1 = np.zeros(thresholds.size)
    for i, thresh in enumerate(thresholds):
        f1[i] = 0.0 if precision[i] + recall[i] == 0 else 2 * precision[i] * recall[i] / (precision[i] + recall[i])
    return float(thresholds[int(np.argmax(f1))])


def review_operating_point(y_true: np.ndarray, scores: np.ndarray, review_at: float) -> dict[str, float]:
    """Review/block if score >= review_at. Reports fraud catch vs extra reviews."""
    flagged = scores >= review_at
    fraud = y_true == 1
    legit = y_true == 0
    caught = int(np.sum(flagged & fraud))
    fraud_n = int(np.sum(fraud))
    legit_n = int(np.sum(legit))
    extra = int(np.sum(flagged & legit))
    return {
        "review_at": float(review_at),
        "fraud_caught": caught,
        "fraud_recall": caught / fraud_n if fraud_n else 0.0,
        "legit_review_rate": extra / legit_n if legit_n else 0.0,
        "precision": caught / int(np.sum(flagged)) if int(np.sum(flagged)) else 0.0,
    }


def recall_at_fpr(y_true: np.ndarray, scores: np.ndarray, fpr_target: float = 0.05) -> dict[str, float]:
    """Highest recall whose false-positive rate is at most fpr_target."""
    legit = y_true == 0
    fraud = y_true == 1
    legit_n = int(np.sum(legit))
    fraud_n = int(np.sum(fraud))
    best = {"fpr_target": float(fpr_target), "threshold": 1.0, "fpr": 0.0, "recall": 0.0}
    if legit_n == 0 or scores.size == 0:
        return best
    for thresh in np.unique(scores):
        flagged = scores >= thresh
        fpr = float(np.sum(flagged & legit) / legit_n)
        if fpr > fpr_target:
            continue
        rec = float(np.sum(flagged & fraud) / fraud_n) if fraud_n else 0.0
        if rec >= best["recall"]:
            best = {"fpr_target": float(fpr_target), "threshold": float(thresh), "fpr": fpr, "recall": rec}
    return best


def brier_and_reliability(y_true: np.ndarray, scores: np.ndarray, bins: int = 10) -> dict[str, Any]:
    if y_true.size == 0:
        return {"brier": None, "bins": []}
    brier = float(brier_score_loss(y_true, np.clip(scores, 0.0, 1.0)))
    edges = np.linspace(0.0, 1.0, bins + 1)
    rows = []
    for i in range(bins):
        mask = (scores >= edges[i]) & (scores < edges[i + 1] if i < bins - 1 else scores <= edges[i + 1])
        if not np.any(mask):
            continue
        rows.append(
            {
                "bin_left": float(edges[i]),
                "bin_right": float(edges[i + 1]),
                "mean_predicted": float(np.mean(scores[mask])),
                "mean_actual": float(np.mean(y_true[mask])),
                "n": int(np.sum(mask)),
            }
        )
    return {"brier": brier, "bins": rows}


def _pack_clf_metrics(y_true: np.ndarray, scores: np.ndarray, thresh: float) -> dict[str, float]:
    predicted = (scores >= thresh).astype(np.int32)
    return {
        "threshold": float(thresh),
        "precision": float(precision_score(y_true, predicted, zero_division=0)),
        "recall": float(recall_score(y_true, predicted, zero_division=0)),
        "f1": float(f1_score(y_true, predicted, zero_division=0)),
        "average_precision": float(average_precision_score(y_true, scores)) if len(np.unique(y_true)) > 1 else float("nan"),
        "roc_auc": float(roc_auc_score(y_true, scores)) if len(np.unique(y_true)) > 1 else float("nan"),
        "brier": float(brier_score_loss(y_true, np.clip(scores, 0.0, 1.0))) if y_true.size else float("nan"),
        "recall_at_5pct_fpr": recall_at_fpr(y_true, scores, 0.05),
        "review": review_operating_point(y_true, scores, thresh),
    }


def _smote_train(x_train: np.ndarray, y_train: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    counts = np.bincount(y_train.astype(int), minlength=2)
    minority = int(counts.min())
    if minority < 2:
        logger.warning("SMOTE skipped — minority class has %s rows", minority)
        return x_train, y_train
    k_neighbors = min(5, minority - 1)
    sampler = SMOTE(random_state=RANDOM_SEED, k_neighbors=k_neighbors)
    return sampler.fit_resample(x_train, y_train)


def train() -> dict[str, float]:
    paysim, _upi = build_feature_frames()
    # UPI statement file has no fraud labels — keep it out of scored evaluation.
    train_df, val_df, test_df = chronological_thirds(paysim)
    feature_cols = list(LIVE_FEATURE_NAMES)
    leaks = _leakage_correlations(train_df, feature_cols)
    hot = {name: corr for name, corr in leaks.items() if abs(corr) >= 0.9}
    if hot:
        logger.warning("high label correlation (possible leak): %s", hot)

    x_train = train_df[feature_cols].to_numpy(dtype=np.float32)
    y_train = train_df["_y"].to_numpy(dtype=np.int32)
    x_val = val_df[feature_cols].to_numpy(dtype=np.float32)
    y_val = val_df["_y"].to_numpy(dtype=np.int32)
    x_test = test_df[feature_cols].to_numpy(dtype=np.float32)
    y_test = test_df["_y"].to_numpy(dtype=np.int32)

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

    metrics = {
        "evaluation": "synthetic_paysim",
        "split": "chronological_60_20_20",
        "precision": xgb_metrics["precision"],
        "recall": xgb_metrics["recall"],
        "f1": xgb_metrics["f1"],
        "roc_auc": xgb_metrics["roc_auc"],
        "average_precision": xgb_metrics["average_precision"],
        "threshold": xgb_metrics["threshold"],
        "review": xgb_metrics["review"],
        "baselines": {"rules": rule_metrics, "logistic_regression": lr_metrics, "xgboost": xgb_metrics},
        "feature_names": list(LIVE_FEATURE_NAMES),
        "max_abs_label_corr": max((abs(v) for v in leaks.values()), default=0.0),
        "high_corr_features": hot,
        "geo_leak": False,
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
        "limitations": [
            "Synthetic-data evaluation (PaySim). Not a real UPI fraud holdout.",
            "No labeled historical UPI set was available; statement CSV is unlabeled and unused for metrics.",
            "CASH_OUT / full-drain flags excluded from ML to avoid simulator label leakage.",
            "Thresholds tuned on a later chronological slice; newest slice is the test report.",
            "Experimental — not a certified fraud detector.",
            "PaySim fraud is time-clustered; the newest slice can be mostly fraud, so PR/review rates are not a real UPI false-positive rate.",
            "Not production-ready: synthetic labels, no UPI ATO labels, calibration is experimental.",
        ],
    }
    print(f"evaluation=synthetic_paysim split=60/20/20")
    print(f"xgb precision={xgb_metrics['precision']:.4f} recall={xgb_metrics['recall']:.4f} ap={xgb_metrics['average_precision']:.4f}")
    print(f"lr  precision={lr_metrics['precision']:.4f} recall={lr_metrics['recall']:.4f} ap={lr_metrics['average_precision']:.4f}")
    print(f"rules precision={rule_metrics['precision']:.4f} recall={rule_metrics['recall']:.4f} ap={rule_metrics['average_precision']:.4f}")
    print(f"review fraud_recall={xgb_metrics['review']['fraud_recall']:.4f} legit_review_rate={xgb_metrics['review']['legit_review_rate']:.4f}")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "feature_names": list(LIVE_FEATURE_NAMES), "version": "xgb_v3"}, MODEL_PATH)
    METRICS_PATH.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"saved model -> {MODEL_PATH}")
    print(f"saved metrics -> {METRICS_PATH}")
    return metrics


if __name__ == "__main__":
    train()
