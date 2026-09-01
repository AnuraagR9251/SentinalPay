"""Input validation for the scoring engine.

Incoming transaction dicts are untrusted — they will eventually arrive
over HTTP. Malformed amounts, missing IDs, and out-of-range coordinates
must fail loudly with `ScoringValidationError` rather than being coerced
into a silent wrong score.
"""

from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping, Sequence

from detection.models import Transaction, UserProfile

_REQUIRED_TXN_FIELDS: tuple[str, ...] = (
    "transaction_id",
    "user_id",
    "amount",
    "payee_vpa",
    "timestamp",
)


class ScoringValidationError(ValueError):
    """Raised when a transaction, history item, or profile cannot be scored."""


def _require_non_empty_str(value: Any, field_name: str) -> str:
    if value is None or not isinstance(value, str) or not value.strip():
        raise ScoringValidationError(f"{field_name} is required and must be a non-empty string")
    return value.strip()


def _parse_amount(value: Any) -> float:
    if isinstance(value, bool) or value is None:
        raise ScoringValidationError("amount must be a positive finite number")
    try:
        amount = float(value)
    except (TypeError, ValueError) as exc:
        raise ScoringValidationError("amount must be a positive finite number") from exc
    if not isfinite(amount) or amount <= 0:
        raise ScoringValidationError("amount must be a positive finite number")
    return amount


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        ts = value
    elif isinstance(value, str) and value.strip():
        try:
            ts = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise ScoringValidationError("timestamp must be ISO-8601 or a datetime") from exc
    else:
        raise ScoringValidationError("timestamp must be ISO-8601 or a datetime")
    # Naive datetimes are treated as UTC. Callers that already have a timezone
    # keep it; we normalise everything to UTC so velocity windows are correct.
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _parse_optional_coord(value: Any, field_name: str, lo: float, hi: float) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ScoringValidationError(f"{field_name} is out of range")
    try:
        coord = float(value)
    except (TypeError, ValueError) as exc:
        raise ScoringValidationError(f"{field_name} is out of range") from exc
    if not isfinite(coord) or coord < lo or coord > hi:
        raise ScoringValidationError(f"{field_name} is out of range")
    return coord


def _parse_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ScoringValidationError("optional string field has an invalid type")
    stripped = value.strip()
    return stripped or None


def _parse_optional_balance(value: Any, field_name: str) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ScoringValidationError(f"{field_name} must be a non-negative finite number")
    try:
        amount = float(value)
    except (TypeError, ValueError) as exc:
        raise ScoringValidationError(f"{field_name} must be a non-negative finite number") from exc
    if not isfinite(amount) or amount < 0:
        raise ScoringValidationError(f"{field_name} must be a non-negative finite number")
    return amount


def parse_transaction(raw: Transaction | Mapping[str, Any]) -> Transaction:
    """Validate and normalise one transaction (dataclass or dict)."""
    if isinstance(raw, Transaction):
        # Re-run through the parser so a constructed-but-invalid dataclass
        # (negative amount, bad coords) cannot bypass checks.
        raw = {
            "transaction_id": raw.transaction_id,
            "user_id": raw.user_id,
            "amount": raw.amount,
            "payee_vpa": raw.payee_vpa,
            "timestamp": raw.timestamp,
            "lat": raw.lat,
            "lon": raw.lon,
            "payee_lat": raw.payee_lat,
            "payee_lon": raw.payee_lon,
            "ip_address": raw.ip_address,
            "device_id": raw.device_id,
            "purpose": raw.purpose,
            "origin_balance": raw.origin_balance,
            "new_origin_balance": raw.new_origin_balance,
            "dest_balance": raw.dest_balance,
            "new_dest_balance": raw.new_dest_balance,
        }

    if not isinstance(raw, Mapping):
        raise ScoringValidationError("transaction must be a mapping or Transaction")

    missing = [name for name in _REQUIRED_TXN_FIELDS if name not in raw or raw[name] in (None, "")]
    if missing:
        raise ScoringValidationError(f"missing required field(s): {', '.join(missing)}")

    lat = _parse_optional_coord(raw.get("lat"), "lat", -90.0, 90.0)
    lon = _parse_optional_coord(raw.get("lon"), "lon", -180.0, 180.0)
    if (lat is None) ^ (lon is None):
        raise ScoringValidationError("lat and lon must both be provided or both omitted")
    payee_lat = _parse_optional_coord(raw.get("payee_lat"), "payee_lat", -90.0, 90.0)
    payee_lon = _parse_optional_coord(raw.get("payee_lon"), "payee_lon", -180.0, 180.0)
    if (payee_lat is None) ^ (payee_lon is None):
        raise ScoringValidationError("payee_lat and payee_lon must both be provided or both omitted")

    return Transaction(
        transaction_id=_require_non_empty_str(raw["transaction_id"], "transaction_id"),
        user_id=_require_non_empty_str(raw["user_id"], "user_id"),
        amount=_parse_amount(raw["amount"]),
        payee_vpa=_require_non_empty_str(raw["payee_vpa"], "payee_vpa"),
        timestamp=_parse_timestamp(raw["timestamp"]),
        lat=lat,
        lon=lon,
        payee_lat=payee_lat,
        payee_lon=payee_lon,
        ip_address=_parse_optional_str(raw.get("ip_address")),
        device_id=_parse_optional_str(raw.get("device_id")),
        purpose=_parse_optional_str(raw.get("purpose")),
        origin_balance=_parse_optional_balance(raw.get("origin_balance"), "origin_balance"),
        new_origin_balance=_parse_optional_balance(raw.get("new_origin_balance"), "new_origin_balance"),
        dest_balance=_parse_optional_balance(raw.get("dest_balance"), "dest_balance"),
        new_dest_balance=_parse_optional_balance(raw.get("new_dest_balance"), "new_dest_balance"),
    )


def parse_history(raw_history: Sequence[Transaction | Mapping[str, Any]] | None) -> tuple[Transaction, ...]:
    """Validate every history item. Malformed rows fail the whole call.

    Silently dropping a bad history row would hide data-quality issues and
    could under-score a takeover. Empty history is valid (new user).
    """
    if raw_history is None:
        return ()
    if isinstance(raw_history, (str, bytes)) or not isinstance(raw_history, Sequence):
        raise ScoringValidationError("history must be a sequence of transactions")
    return tuple(parse_transaction(item) for item in raw_history)


def parse_user_profile(raw: UserProfile | Mapping[str, Any]) -> UserProfile:
    """Validate the user profile used as scoring context."""
    if isinstance(raw, UserProfile):
        raw = {
            "user_id": raw.user_id,
            "home_lat": raw.home_lat,
            "home_lon": raw.home_lon,
            "known_payees": raw.known_payees,
        }
    if not isinstance(raw, Mapping):
        raise ScoringValidationError("user_profile must be a mapping or UserProfile")

    home_lat = _parse_optional_coord(raw.get("home_lat"), "home_lat", -90.0, 90.0)
    home_lon = _parse_optional_coord(raw.get("home_lon"), "home_lon", -180.0, 180.0)
    if (home_lat is None) ^ (home_lon is None):
        raise ScoringValidationError("home_lat and home_lon must both be provided or both omitted")

    known_raw = raw.get("known_payees") or ()
    if isinstance(known_raw, str):
        raise ScoringValidationError("known_payees must be a collection of VPA strings")
    try:
        known_payees = frozenset(str(v).strip() for v in known_raw if str(v).strip())
    except TypeError as exc:
        raise ScoringValidationError("known_payees must be a collection of VPA strings") from exc

    return UserProfile(
        user_id=_require_non_empty_str(raw.get("user_id"), "user_id"),
        home_lat=home_lat,
        home_lon=home_lon,
        known_payees=known_payees,
    )
