"""Turn a raw payment dict into NormalizedTransaction. No scoring here."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping

from risk.contracts import NormalizedTransaction

_CATEGORY_ALIASES = {
    "electronic": "electronics",
    "electronics": "electronics",
    "grocery": "groceries",
    "groceries": "groceries",
    "food": "dining",
    "dining": "dining",
    "crypto": "crypto",
    "gambling": "gambling",
    "jewellery": "jewelry",
    "jewelry": "jewelry",
    "transfer": "p2p",
    "p2p": "p2p",
}


class NormalizationError(ValueError):
    """Malformed or unusable payment payload."""


def _require_str(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if value is None or not str(value).strip():
        raise NormalizationError(f"{key} is required")
    return str(value).strip()


def _optional_str(raw: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = raw.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _amount(raw: Mapping[str, Any]) -> float:
    try:
        amount = float(raw.get("amount"))
    except (TypeError, ValueError) as exc:
        raise NormalizationError("amount must be a positive number") from exc
    if not isfinite(amount) or amount <= 0:
        raise NormalizationError("amount must be a positive finite number")
    return round(amount, 2)


def _coord(raw: Mapping[str, Any], *keys: str, lo: float, hi: float) -> float | None:
    for key in keys:
        if key not in raw or raw[key] in (None, ""):
            continue
        try:
            value = float(raw[key])
        except (TypeError, ValueError) as exc:
            raise NormalizationError(f"{key} must be a number") from exc
        if not isfinite(value) or value < lo or value > hi:
            raise NormalizationError(f"{key} out of range")
        return value
    return None


def _timestamp(raw: Mapping[str, Any]) -> datetime:
    value = raw.get("timestamp")
    if value is None or value == "":
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        ts = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        try:
            ts = datetime.fromisoformat(text)
        except ValueError as exc:
            raise NormalizationError("timestamp must be ISO-8601") from exc
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def normalize_transaction(raw: Mapping[str, Any]) -> NormalizedTransaction:
    txn_id = _optional_str(raw, "transaction_id") or f"TXN_{uuid.uuid4().hex[:12]}"
    user_id = _require_str(raw, "user_id")
    merchant = _optional_str(raw, "merchant_id", "payee_vpa") or "unknown_merchant"
    category_raw = (_optional_str(raw, "merchant_category", "purpose") or "general").lower()
    category = _CATEGORY_ALIASES.get(category_raw, category_raw)
    currency = (_optional_str(raw, "currency") or "INR").upper()
    if currency != "INR":
        raise NormalizationError("only INR is supported")
    failures = raw.get("recent_failures", raw.get("failed_attempts_last_hour", 0)) or 0
    try:
        recent_failures = int(failures)
    except (TypeError, ValueError) as exc:
        raise NormalizationError("recent_failures must be an integer") from exc
    if recent_failures < 0:
        raise NormalizationError("recent_failures cannot be negative")
    lat = _coord(raw, "latitude", "lat", lo=-90.0, hi=90.0)
    lon = _coord(raw, "longitude", "lon", lo=-180.0, hi=180.0)
    if (lat is None) ^ (lon is None):
        raise NormalizationError("latitude and longitude must be provided together")
    return NormalizedTransaction(
        transaction_id=txn_id,
        user_id=user_id,
        amount=_amount(raw),
        currency=currency,
        merchant_id=merchant,
        merchant_category=category,
        timestamp=_timestamp(raw),
        device_id=_optional_str(raw, "device_id"),
        ip_address=_optional_str(raw, "ip_address"),
        latitude=lat,
        longitude=lon,
        recent_failures=recent_failures,
    )
