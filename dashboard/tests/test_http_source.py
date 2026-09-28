"""HttpTransactionSource maps GET /transactions JSON into desk pairs."""

from datetime import datetime, timezone

from dashboard.data_simulator import rows_from_feed


def test_rows_from_feed_maps_live_payment() -> None:
    pairs = rows_from_feed(
        [
            {
                "transaction_id": "tx-1",
                "user_id": "aarav@senitenial",
                "amount": 240.0,
                "payee_vpa": "priya.p@oksbi",
                "timestamp": "2026-09-28T10:00:00+00:00",
                "lat": 18.52,
                "lon": 73.85,
                "purpose": "Dining",
                "risk_score": 0.12,
                "risk_tier": "ALLOW",
                "P_xgb": 0.01,
                "P_ae": 0.1,
                "P_graph": 0.02,
                "P_hybrid": 0.12,
                "contributions": [{"name": "new_payee", "value": 0.0}],
            }
        ]
    )
    assert len(pairs) == 1
    txn, assessment = pairs[0]
    assert txn.payee_vpa == "priya.p@oksbi"
    assert txn.timestamp == datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc)
    assert assessment.score == 0.12
    assert assessment.p_hybrid == 0.12
    assert assessment.tier.value == "ALLOW"


def test_rows_from_feed_skips_bad_rows() -> None:
    pairs = rows_from_feed(
        [
            {"transaction_id": "bad", "amount": -1, "timestamp": "2026-01-01T00:00:00Z"},
            "nope",
        ]
    )
    assert pairs == []
