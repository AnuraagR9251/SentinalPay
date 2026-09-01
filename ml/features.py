"""Shared feature builder for the 3-class payment-risk model.

Features are deliberately free of raw PII (no VPA, merchant name, device,
or coordinates). Purpose/category is encoded as a coarse payment intent
so the model can learn that cash-out and large P2P behave differently
from grocery UPI.
"""

from __future__ import annotations

from datetime import datetime
from math import log1p
from typing import Any, Mapping, Optional, Protocol

import numpy as np

LABEL_LEGIT = "LEGIT"
LABEL_SUSPICIOUS = "SUSPICIOUS"
LABEL_LIKELY_FRAUD = "LIKELY_FRAUD"
LABELS: tuple[str, ...] = (LABEL_LEGIT, LABEL_SUSPICIOUS, LABEL_LIKELY_FRAUD)
LABEL_TO_ID: dict[str, int] = {label: idx for idx, label in enumerate(LABELS)}
ID_TO_LABEL: dict[int, str] = {idx: label for idx, label in enumerate(LABELS)}


class _TxnLike(Protocol):
    amount: float
    timestamp: Any
    purpose: Optional[str]
    origin_balance: Optional[float]
    new_origin_balance: Optional[float]
    dest_balance: Optional[float]
    new_dest_balance: Optional[float]

PURPOSE_VOCAB: tuple[str, ...] = (
    "merchant_payment",
    "p2p_transfer",
    "cash_out",
    "cash_in",
    "debit",
    "bill_payment",
    "salary",
    "investment",
    "other",
)

_PAYSIM_TYPE_TO_PURPOSE: dict[str, str] = {
    "PAYMENT": "merchant_payment",
    "TRANSFER": "p2p_transfer",
    "CASH_OUT": "cash_out",
    "CASH_IN": "cash_in",
    "DEBIT": "debit",
}

_UPI_TYPE_TO_PURPOSE: dict[str, str] = {
    "upi payment": "merchant_payment",
    "peer transfer": "p2p_transfer",
    "bill payment": "bill_payment",
    "investment": "investment",
    "salary credit": "salary",
    "refund": "cash_in",
    "cashback": "cash_in",
    "interest": "cash_in",
}

_UPI_CATEGORY_TO_PURPOSE: dict[str, str] = {
    "food & dining": "merchant_payment",
    "food delivery": "merchant_payment",
    "groceries": "merchant_payment",
    "transport": "merchant_payment",
    "healthcare": "merchant_payment",
    "quick commerce": "merchant_payment",
    "shopping": "merchant_payment",
    "entertainment": "merchant_payment",
    "utilities": "bill_payment",
    "mobile & internet": "bill_payment",
    "fuel": "merchant_payment",
    "travel": "merchant_payment",
    "housing": "bill_payment",
    "personal transfer": "p2p_transfer",
    "investment": "investment",
    "savings": "investment",
    "salary": "salary",
    "refund": "cash_in",
    "cashback": "cash_in",
    "interest": "cash_in",
}

FEATURE_NAMES: tuple[str, ...] = (
    "amount",
    "log_amount",
    "hour",
    "is_weekend",
    "has_balances",
    "origin_balance",
    "new_origin_balance",
    "dest_balance",
    "new_dest_balance",
    "amount_to_origin_ratio",
    "error_orig",
    "error_dest",
    "dest_is_merchant",
    "is_full_drain",
    "category_amount_ratio",
    *(f"purpose_{name}" for name in PURPOSE_VOCAB),
)

MISSING: float = 0.0


def normalise_purpose(
    purpose: Optional[str] = None,
    *,
    paysim_type: Optional[str] = None,
    upi_type: Optional[str] = None,
    category: Optional[str] = None,
) -> str:
    """Map raw dataset fields onto the shared purpose vocabulary."""
    if purpose:
        key = purpose.strip().lower().replace(" ", "_")
        if key in PURPOSE_VOCAB:
            return key
        mapped = _PAYSIM_TYPE_TO_PURPOSE.get(purpose.strip().upper())
        if mapped:
            return mapped
        mapped = _UPI_TYPE_TO_PURPOSE.get(purpose.strip().lower())
        if mapped:
            return mapped
    if paysim_type:
        mapped = _PAYSIM_TYPE_TO_PURPOSE.get(paysim_type.strip().upper())
        if mapped:
            return mapped
    if upi_type:
        mapped = _UPI_TYPE_TO_PURPOSE.get(upi_type.strip().lower())
        if mapped:
            return mapped
    if category:
        mapped = _UPI_CATEGORY_TO_PURPOSE.get(category.strip().lower())
        if mapped:
            return mapped
    return "other"


def _safe_float(value: Any, default: float = MISSING) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):  # NaN / inf
        return default
    return number


def vector_from_mapping(
    row: Mapping[str, Any],
    *,
    category_medians: Optional[Mapping[str, float]] = None,
) -> np.ndarray:
    """Build one numeric feature row from a training or inference mapping."""
    amount = max(0.0, _safe_float(row.get("amount")))
    purpose = normalise_purpose(
        row.get("purpose"),
        paysim_type=row.get("paysim_type"),
        upi_type=row.get("upi_type"),
        category=row.get("category"),
    )
    hour = int(_safe_float(row.get("hour"), 12.0)) % 24
    is_weekend = 1.0 if _safe_float(row.get("is_weekend")) >= 1 else 0.0

    origin = row.get("origin_balance")
    new_origin = row.get("new_origin_balance")
    dest = row.get("dest_balance")
    new_dest = row.get("new_dest_balance")
    has_balances = 1.0 if origin is not None and new_origin is not None else 0.0
    origin_f = _safe_float(origin) if origin is not None else MISSING
    new_origin_f = _safe_float(new_origin) if new_origin is not None else MISSING
    dest_f = _safe_float(dest) if dest is not None else MISSING
    new_dest_f = _safe_float(new_dest) if new_dest is not None else MISSING

    ratio = amount / (origin_f + 1.0) if has_balances else MISSING
    error_orig = (origin_f - amount - new_origin_f) if has_balances else MISSING
    error_dest = (dest_f + amount - new_dest_f) if has_balances else MISSING
    dest_is_merchant = 1.0 if _safe_float(row.get("dest_is_merchant")) >= 1 else 0.0
    is_full_drain = (
        1.0
        if has_balances and origin_f > 0 and new_origin_f <= 1e-6 and abs(origin_f - amount) <= 1.0
        else 0.0
    )

    median = 0.0
    if category_medians:
        median = float(category_medians.get(purpose, 0.0) or 0.0)
    category_ratio = amount / median if median > 0 else 1.0

    purpose_oh = [1.0 if purpose == name else 0.0 for name in PURPOSE_VOCAB]
    values = [
        amount,
        log1p(amount),
        float(hour),
        is_weekend,
        has_balances,
        origin_f,
        new_origin_f,
        dest_f,
        new_dest_f,
        ratio,
        error_orig,
        error_dest,
        dest_is_merchant,
        is_full_drain,
        category_ratio,
        *purpose_oh,
    ]
    return np.asarray(values, dtype=np.float32)


def vector_from_transaction(
    transaction: _TxnLike,
    *,
    category_medians: Optional[Mapping[str, float]] = None,
) -> np.ndarray:
    """Inference path: Transaction → model vector (no PII fields)."""
    ts: datetime = transaction.timestamp
    return vector_from_mapping(
        {
            "amount": transaction.amount,
            "purpose": transaction.purpose,
            "hour": ts.hour,
            "is_weekend": 1 if ts.weekday() >= 5 else 0,
            "origin_balance": transaction.origin_balance,
            "new_origin_balance": transaction.new_origin_balance,
            "dest_balance": transaction.dest_balance,
            "new_dest_balance": transaction.new_dest_balance,
            "dest_is_merchant": 0 if (transaction.purpose or "") in {"p2p_transfer", "cash_out"} else 1,
        },
        category_medians=category_medians,
    )


def drop_balance_features(row: Mapping[str, Any]) -> dict[str, Any]:
    """Augmentation: hide ledger fields so the model can score UPI-like rows."""
    copied = dict(row)
    for key in (
        "origin_balance",
        "new_origin_balance",
        "dest_balance",
        "new_dest_balance",
        "dest_is_merchant",
    ):
        copied[key] = None
    copied["dest_is_merchant"] = 0
    return copied
