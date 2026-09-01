"""Build a 3-class training table from the uploaded datasets.

Label policy (documented so the academic report can defend it):

* PaySim ``isFraud == 1`` → LIKELY_FRAUD (the only hard fraud labels).
* PaySim ``isFlaggedFraud == 1`` or a large non-fraud TRANSFER/CASH_OUT
  (≥ ₹2,00,000, PaySim's own flag threshold) → SUSPICIOUS.
* Remaining PaySim traffic, down-sampled → LEGIT.
* UPI 2025 statement has no fraud labels. Everyday successful spend is
  LEGIT; failed rows, large peer transfers, and category outliers are
  weak-labeled SUSPICIOUS. Merchant names are never written to disk.
* The Excel workbook has Age/City/App/Spending_Category only — used for
  purpose vocabulary, not as fraud training rows.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Iterator

import numpy as np
import pandas as pd

from ml.features import (
    LABEL_LIKELY_FRAUD,
    LABEL_LEGIT,
    LABEL_SUSPICIOUS,
    LABEL_TO_ID,
    drop_balance_features,
    normalise_purpose,
    vector_from_mapping,
)

logger = logging.getLogger("sentinalpay.ml.prepare")

REPO_ROOT = Path(__file__).resolve().parent.parent
DATASET_DIR = REPO_ROOT / "dataset"
PAYSIM_NAME = "PS_20174392719_1491204439457_log.csv"
UPI_CSV_NAME = "upi_transactions_2025.csv"
UPI_XLSX_NAME = "upi_digital_payment_dataset.xlsx"

SUSPICIOUS_AMOUNT: float = 200_000.0
UPI_P2P_SUSPICIOUS: float = 15_000.0
LEGIT_CAP: int = 28_000
SUSPICIOUS_CAP: int = 12_000
CHUNK_SIZE: int = 250_000
RANDOM_SEED: int = 7102


def _paysim_path() -> Path:
    path = DATASET_DIR / PAYSIM_NAME
    if not path.exists():
        raise FileNotFoundError(f"PaySim log not found at {path}")
    return path


def _iter_paysim() -> Iterator[pd.DataFrame]:
    yield from pd.read_csv(_paysim_path(), chunksize=CHUNK_SIZE)


def _df_to_feature_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    dest = frame["nameDest"].astype(str).to_numpy()
    types = frame["type"].astype(str).to_numpy()
    amounts = frame["amount"].to_numpy(dtype=np.float64)
    steps = frame["step"].to_numpy(dtype=np.int64)
    old_org = frame["oldbalanceOrg"].to_numpy(dtype=np.float64)
    new_org = frame["newbalanceOrig"].to_numpy(dtype=np.float64)
    old_dst = frame["oldbalanceDest"].to_numpy(dtype=np.float64)
    new_dst = frame["newbalanceDest"].to_numpy(dtype=np.float64)
    rows: list[dict[str, Any]] = []
    for i in range(len(frame)):
        rows.append(
            {
                "amount": float(amounts[i]),
                "paysim_type": str(types[i]),
                "purpose": normalise_purpose(paysim_type=str(types[i])),
                "hour": int(steps[i]) % 24,
                "is_weekend": 0,
                "origin_balance": float(old_org[i]),
                "new_origin_balance": float(new_org[i]),
                "dest_balance": float(old_dst[i]),
                "new_dest_balance": float(new_dst[i]),
                "dest_is_merchant": 1 if dest[i].startswith("M") else 0,
            }
        )
    return rows


def _reservoir_merge(
    store: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
    cap: int,
    seen: list[int],
    rng: np.random.Generator,
) -> None:
    for item in incoming:
        seen[0] += 1
        if len(store) < cap:
            store.append(item)
            continue
        idx = int(rng.integers(0, seen[0]))
        if idx < cap:
            store[idx] = item


def load_upi_category_medians() -> dict[str, float]:
    """Median amount per purpose from the UPI statement (no merchant names)."""
    path = DATASET_DIR / UPI_CSV_NAME
    if not path.exists():
        return {}
    frame = pd.read_csv(path, usecols=["Category", "Transaction_Type", "Amount"])
    purposes = [
        normalise_purpose(upi_type=str(t), category=str(c))
        for t, c in zip(frame["Transaction_Type"], frame["Category"])
    ]
    tmp = pd.DataFrame({"purpose": purposes, "amount": frame["Amount"]})
    return tmp.groupby("purpose")["amount"].median().to_dict()


def _weak_label_upi(row: pd.Series, category_p99: dict[str, float]) -> str:
    status = str(row["Status"]).strip().lower()
    txn_type = str(row["Transaction_Type"])
    category = str(row["Category"])
    amount = float(row["Amount"])
    purpose = normalise_purpose(upi_type=txn_type, category=category)
    if status == "failed":
        return LABEL_SUSPICIOUS
    if purpose == "p2p_transfer" and amount >= UPI_P2P_SUSPICIOUS:
        return LABEL_SUSPICIOUS
    if amount >= category_p99.get(purpose, float("inf")):
        return LABEL_SUSPICIOUS
    return LABEL_LEGIT


def load_upi_labeled_rows() -> list[tuple[dict[str, Any], str]]:
    path = DATASET_DIR / UPI_CSV_NAME
    if not path.exists():
        logger.warning("UPI CSV missing — training on PaySim only")
        return []
    frame = pd.read_csv(path)
    purposes = [
        normalise_purpose(upi_type=str(t), category=str(c))
        for t, c in zip(frame["Transaction_Type"], frame["Category"])
    ]
    frame = frame.assign(_purpose=purposes)
    p99 = frame.groupby("_purpose")["Amount"].quantile(0.995).to_dict()
    labeled: list[tuple[dict[str, Any], str]] = []
    for _, row in frame.iterrows():
        debit = float(row["Debit"])
        credit = float(row["Credit"])
        available = float(row["Available_Balance"])
        if debit > 0:
            origin = available + debit
            new_origin = available
        else:
            origin = max(0.0, available - credit)
            new_origin = available
        hour = 12
        try:
            hour = int(str(row["Time"]).split(":")[0])
        except (TypeError, ValueError, IndexError):
            hour = 12
        weekday = 0
        try:
            weekday = int(pd.Timestamp(row["Date"]).dayofweek >= 5)
        except (TypeError, ValueError):
            weekday = 0
        features = {
            "amount": float(row["Amount"]),
            "purpose": row["_purpose"],
            "upi_type": str(row["Transaction_Type"]),
            "category": str(row["Category"]),
            "hour": hour,
            "is_weekend": weekday,
            "origin_balance": origin,
            "new_origin_balance": new_origin,
            "dest_balance": None,
            "new_dest_balance": None,
            "dest_is_merchant": 0 if row["_purpose"] == "p2p_transfer" else 1,
        }
        labeled.append((features, _weak_label_upi(row, p99)))
    return labeled


def note_xlsx_scope() -> None:
    path = DATASET_DIR / UPI_XLSX_NAME
    if not path.exists():
        return
    try:
        frame = pd.read_excel(path, sheet_name="Dataset")
    except Exception as exc:  # noqa: BLE001 — training must not die on a side workbook
        logger.warning("Could not read UPI xlsx: %s", type(exc).__name__)
        return
    logger.info(
        "xlsx rows=%s cols=%s — no fraud labels, not used as training y",
        len(frame),
        list(frame.columns),
    )


def collect_training_frame() -> tuple[np.ndarray, np.ndarray, dict[str, float]]:
    """Stream PaySim + UPI into X, y. Logs class counts only (no PII)."""
    rng = np.random.default_rng(RANDOM_SEED)
    fraud: list[dict[str, Any]] = []
    suspicious: list[dict[str, Any]] = []
    legit: list[dict[str, Any]] = []
    seen_susp = [0]
    seen_legit = [0]

    for chunk in _iter_paysim():
        fraud.extend(_df_to_feature_rows(chunk.loc[chunk["isFraud"] == 1]))
        susp_mask = (chunk["isFraud"] == 0) & (
            (chunk["isFlaggedFraud"] == 1)
            | (chunk["type"].isin(["TRANSFER", "CASH_OUT"]) & (chunk["amount"] >= SUSPICIOUS_AMOUNT))
        )
        legit_mask = (chunk["isFraud"] == 0) & ~susp_mask
        susp_df = chunk.loc[susp_mask]
        legit_df = chunk.loc[legit_mask]
        if len(susp_df) > 2500:
            susp_df = susp_df.sample(n=2500, random_state=int(rng.integers(0, 10_000)))
        if len(legit_df) > 4000:
            legit_df = legit_df.sample(n=4000, random_state=int(rng.integers(0, 10_000)))
        _reservoir_merge(suspicious, _df_to_feature_rows(susp_df), SUSPICIOUS_CAP, seen_susp, rng)
        _reservoir_merge(legit, _df_to_feature_rows(legit_df), LEGIT_CAP, seen_legit, rng)

    upi_rows = load_upi_labeled_rows()
    for features, label in upi_rows:
        if label == LABEL_SUSPICIOUS:
            suspicious.append(features)
        else:
            legit.append(features)

    note_xlsx_scope()
    medians = load_upi_category_medians()

    rows: list[dict[str, Any]] = []
    labels: list[str] = []
    for features in fraud:
        rows.append(features)
        labels.append(LABEL_LIKELY_FRAUD)
        # Balance-ablated copy so inference works on UPI rows without ledgers.
        rows.append(drop_balance_features(features))
        labels.append(LABEL_LIKELY_FRAUD)
    for features in suspicious:
        rows.append(features)
        labels.append(LABEL_SUSPICIOUS)
    for features in legit:
        rows.append(features)
        labels.append(LABEL_LEGIT)

    matrix = np.vstack([vector_from_mapping(row, category_medians=medians) for row in rows])
    y = np.asarray([LABEL_TO_ID[label] for label in labels], dtype=np.int32)
    counts = {name: int(np.sum(y == idx)) for name, idx in LABEL_TO_ID.items()}
    logger.info("training class counts=%s rows=%s", counts, len(y))
    return matrix, y, medians
