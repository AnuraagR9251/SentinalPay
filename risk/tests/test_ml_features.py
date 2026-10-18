"""Point-in-time features: history only, no drain-label leak."""

from datetime import datetime, timedelta, timezone

from risk.ml_layer import LIVE_FEATURE_NAMES, engineer_features
from risk.normalize import normalize_transaction


def _txn(amount: float, minutes: int, payee: str = "a@oksbi", device: str = "dev-1"):
    ts = datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes)
    return normalize_transaction(
        {
            "transaction_id": f"t-{minutes}-{amount}",
            "user_id": "USR_FEAT",
            "amount": amount,
            "merchant_id": payee,
            "timestamp": ts.isoformat(),
            "device_id": device,
            "latitude": 12.9716,
            "longitude": 77.5946,
        }
    )


def _row(txn) -> dict:
    return {
        "amount": txn.amount,
        "timestamp": txn.timestamp,
        "merchant_id": txn.merchant_id,
        "device_id": txn.device_id,
        "latitude": txn.latitude,
        "longitude": txn.longitude,
    }


def test_empty_history_is_not_a_spike() -> None:
    vector = engineer_features(_txn(50000, 0), [], home=None)
    assert vector["amount_spike"] == 0.0
    assert vector["new_device"] == 0.0
    assert vector["history_size"] == 0.0
    assert "is_full_drain" not in LIVE_FEATURE_NAMES


def test_median_uses_only_prior_rows() -> None:
    first = _txn(200, 0)
    later = _txn(2000, 10, payee="new@oksbi", device="dev-2")
    vector = engineer_features(later, [_row(first)], home=(12.9716, 77.5946))
    assert vector["amount_to_median"] > 0.0
    assert vector["amount_spike"] > 0.0
    assert vector["recent_device_change"] == 1.0
    assert vector["recipient_prior_count"] == 0.0
    assert vector["location_reliable"] == 1.0


def test_future_history_is_ignored_for_velocity() -> None:
    past = _txn(200, 0)
    now = _txn(200, 2)
    future = _txn(9000, 3)
    with_future = engineer_features(now, [_row(past), _row(future)], home=None)
    without = engineer_features(now, [_row(past)], home=None)
    assert with_future["velocity_5m_value"] == without["velocity_5m_value"]
