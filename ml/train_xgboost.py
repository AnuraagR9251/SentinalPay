"""Train a binary XGBoost fraud classifier on behavioural + location features.

Usage (from repo root):

    python ml/train_xgboost.py
    py -3 ml/train_xgboost.py

Loads the PaySim CSV (hard `isFraud` labels) plus the UPI 2025 statement
as extra legitimate traffic. Split is chronological 80/20 — not random —
so the model cannot peek at future payments. SMOTE is fit on the training
fold only. Features come from `detection.scoring_engine.extract_feature_vector`
(the same functions the live `/score` API uses).
"""

from __future__ import annotations

import hashlib
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
from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score
from xgboost import XGBClassifier

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from detection.scoring_engine import FEATURE_VECTOR_NAMES, extract_feature_vector  # noqa: E402
from detection.validation import ScoringValidationError  # noqa: E402

logging.basicConfig(level=os.getenv("SENTINALPAY_LOG_LEVEL", "INFO"))
logger = logging.getLogger("sentinalpay.ml.xgb")

DATASET_DIR = REPO_ROOT / "dataset"
PAYSIM_PATH = DATASET_DIR / "PS_20174392719_1491204439457_log.csv"
UPI_PATH = DATASET_DIR / "upi_transactions_2025.csv"
MODEL_DIR = REPO_ROOT / "ml" / "models"
MODEL_PATH = MODEL_DIR / "xgboost_model.pkl"

CHUNK_SIZE = 250_000
LEGIT_USER_CAP = 2_500
LEGIT_SEQ_CAP = 16
RANDOM_SEED = 7102
PAYSIM_EPOCH = datetime(2017, 1, 1, tzinfo=timezone.utc)

# Deterministic India city list so location features have variance. PaySim
# has no GPS; fraud rows are placed in a distant city so dist/speed fire.
_CITIES: tuple[tuple[float, float], ...] = (
    (18.5204, 73.8567),  # Pune
    (19.0760, 72.8777),  # Mumbai
    (28.6139, 77.2090),  # Delhi
    (12.9716, 77.5946),  # Bengaluru
    (13.0827, 80.2707),  # Chennai
    (22.5726, 88.3639),  # Kolkata
    (17.3850, 78.4867),  # Hyderabad
)


def _city_for(user_key: str) -> tuple[float, float]:
    digest = hashlib.sha256(user_key.encode("utf-8")).digest()
    return _CITIES[int.from_bytes(digest[:4], "little") % len(_CITIES)]


def _txn_coords(user_key: str, is_fraud: bool, step: int) -> tuple[float, float]:
    home = _city_for(user_key)
    if is_fraud:
        far = _CITIES[(_CITIES.index(home) + 3) % len(_CITIES)]
        return far[0] + 0.01, far[1] + 0.01
    jitter = ((step % 5) - 2) * 0.004
    return home[0] + jitter, home[1] + jitter * 0.6


def _profile(user_id: str) -> dict[str, Any]:
    home = _city_for(user_id)
    return {
        "user_id": user_id,
        "home_lat": home[0],
        "home_lon": home[1],
        "known_payees": (),
    }


def _walk_sequence(
    user_id: str,
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Emit one feature row per event using only prior events as history."""
    events = sorted(events, key=lambda item: item["txn"]["timestamp"])
    profile = _profile(user_id)
    history: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    for event in events:
        try:
            vector = extract_feature_vector(event["txn"], history, profile)
        except ScoringValidationError:
            continue
        rows.append(
            {
                **vector,
                "_y": event["y"],
                "_ts": event["txn"]["timestamp"],
            }
        )
        history.append(event["txn"])
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
    usecols = ["step", "amount", "nameOrig", "nameDest", "isFraud"]

    for chunk in pd.read_csv(PAYSIM_PATH, usecols=usecols, chunksize=CHUNK_SIZE):
        orig = chunk["nameOrig"].astype(str)
        mask = orig.isin(wanted)
        if not mask.any():
            continue
        sub = chunk.loc[mask]
        steps = sub["step"].to_numpy()
        amounts = sub["amount"].to_numpy(dtype=np.float64)
        origins = sub["nameOrig"].astype(str).to_numpy()
        dests = sub["nameDest"].astype(str).to_numpy()
        labels = sub["isFraud"].to_numpy(dtype=np.int8)
        for i in range(len(sub)):
            user_id = origins[i]
            is_fraud = bool(labels[i])
            if float(amounts[i]) <= 0:
                continue
            if user_id not in fraud_users and len(sequences[user_id]) >= LEGIT_SEQ_CAP:
                continue
            lat, lon = _txn_coords(user_id, is_fraud, int(steps[i]))
            txn = {
                "transaction_id": f"ps_{abs(hash(user_id)) % 10_000_000}_{int(steps[i])}_{i}",
                "user_id": user_id,
                "amount": float(amounts[i]),
                "payee_vpa": f"{dests[i]}@ps",
                "timestamp": PAYSIM_EPOCH + timedelta(hours=int(steps[i])),
                "lat": lat,
                "lon": lon,
            }
            sequences[user_id].append({"txn": txn, "y": 1 if is_fraud else 0})
    logger.info("paysim sequences=%s", len(sequences))
    return sequences


def _load_upi_sequence() -> list[dict[str, Any]]:
    if not UPI_PATH.exists():
        logger.warning("UPI CSV missing — training on PaySim only")
        return []
    frame = pd.read_csv(UPI_PATH)
    user_id = "upi_statement_2025"
    events: list[dict[str, Any]] = []
    home = _city_for(user_id)
    for idx, row in frame.iterrows():
        amount = float(row["Amount"])
        if amount <= 0:
            continue
        try:
            ts = datetime.fromisoformat(f"{row['Date']}T{row['Time']}").replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        jitter = ((int(idx) % 5) - 2) * 0.003
        txn = {
            "transaction_id": str(row["Transaction_ID"]),
            "user_id": user_id,
            "amount": amount,
            "payee_vpa": f"merchant_{int(idx) % 40}@upi",
            "timestamp": ts,
            "lat": home[0] + jitter,
            "lon": home[1] + jitter * 0.5,
        }
        events.append({"txn": txn, "y": 0})
    logger.info("upi events=%s", len(events))
    return events


def build_feature_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Walk per-user history. PaySim and UPI stay on their own clocks."""
    paysim_rows: list[dict[str, Any]] = []
    for user_id, events in _load_paysim_sequences().items():
        paysim_rows.extend(_walk_sequence(user_id, events))
    paysim = pd.DataFrame(paysim_rows)
    if paysim.empty:
        raise RuntimeError("no PaySim training rows — check dataset/ CSVs")

    upi_events = _load_upi_sequence()
    upi = pd.DataFrame(_walk_sequence("upi_statement_2025", upi_events)) if upi_events else pd.DataFrame()
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
    paysim, upi = build_feature_frames()
    # Chronological 80/20 per source so 2025 UPI cannot push all PaySim fraud into train.
    train_df, test_df = chronological_split(paysim)
    if not upi.empty:
        upi_train, upi_test = chronological_split(upi)
        train_df = pd.concat([train_df, upi_train], ignore_index=True)
        test_df = pd.concat([test_df, upi_test], ignore_index=True)
    feature_cols = list(FEATURE_VECTOR_NAMES)
    x_train = train_df[feature_cols].to_numpy(dtype=np.float32)
    y_train = train_df["_y"].to_numpy(dtype=np.int32)
    x_test = test_df[feature_cols].to_numpy(dtype=np.float32)
    y_test = test_df["_y"].to_numpy(dtype=np.int32)

    logger.info(
        "split train=%s test=%s train_fraud=%s test_fraud=%s",
        len(y_train),
        len(y_test),
        int(y_train.sum()),
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
        eval_metric="auc",
        tree_method="hist",
        n_jobs=4,
        random_state=RANDOM_SEED,
    )
    model.fit(x_res, y_res)

    proba = model.predict_proba(x_test)[:, 1]
    predicted = (proba >= 0.5).astype(np.int32)
    metrics = {
        "precision": float(precision_score(y_test, predicted, zero_division=0)),
        "recall": float(recall_score(y_test, predicted, zero_division=0)),
        "f1": float(f1_score(y_test, predicted, zero_division=0)),
        "roc_auc": float(roc_auc_score(y_test, proba)) if len(np.unique(y_test)) > 1 else float("nan"),
    }
    print(f"precision={metrics['precision']:.4f}")
    print(f"recall={metrics['recall']:.4f}")
    print(f"f1-score={metrics['f1']:.4f}")
    print(f"roc-auc={metrics['roc_auc']:.4f}")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    print(f"saved model -> {MODEL_PATH}")
    return metrics


if __name__ == "__main__":
    train()
