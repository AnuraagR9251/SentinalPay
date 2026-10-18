"""HttpTransactionSource maps GET /transactions JSON into desk pairs."""

from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError

from dashboard.data_simulator import HttpTransactionSource, merge_feed, rows_from_feed
from detection.models import RiskTier


def _pair(txn_id: str, hour: int, score: float = 0.12, tier: str = "ALLOW"):
    return {
        "transaction_id": txn_id,
        "user_id": "aarav@senitenial",
        "amount": 240.0,
        "payee_vpa": "priya.p@oksbi",
        "timestamp": f"2026-09-28T{hour:02d}:00:00+00:00",
        "lat": 18.52,
        "lon": 73.85,
        "purpose": "Dining",
        "risk_score": score,
        "risk_tier": tier,
        "canonical_decision": "ALLOW" if tier == "ALLOW" else "REVIEW" if tier == "HOLD" else "BLOCK",
        "P_xgb": 0.01,
        "P_ae": None,
        "P_graph": None,
        "P_hybrid": score,
        "ae_available": False,
        "graph_available": False,
        "ml_available": True,
        "contributions": [{"name": "NEW_MERCHANT", "value": 0.4}],
    }


def test_rows_from_feed_maps_live_payment() -> None:
    pairs = rows_from_feed([_pair("tx-1", 10)])
    assert len(pairs) == 1
    txn, assessment = pairs[0]
    assert txn.payee_vpa == "priya.p@oksbi"
    assert txn.timestamp == datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc)
    assert assessment.score == 0.12
    assert assessment.p_hybrid == 0.12
    assert assessment.tier.value == "ALLOW"
    assert assessment.ml_label is None
    assert assessment.p_ae is None
    assert assessment.canonical_decision == "ALLOW"
    assert assessment.ae_available is False


def test_rows_from_feed_skips_bad_rows() -> None:
    pairs = rows_from_feed(
        [
            {"transaction_id": "bad", "amount": -1, "timestamp": "2026-01-01T00:00:00Z"},
            "nope",
            _pair("tx-skip-tier", 11, tier="MAYBE"),
        ]
    )
    assert pairs == []


def test_rows_from_feed_dedupes_and_keeps_null_ae() -> None:
    pairs = rows_from_feed([_pair("tx-dup", 10), _pair("tx-dup", 11)])
    assert len(pairs) == 1
    assert pairs[0][0].transaction_id == "tx-dup"
    assert pairs[0][1].p_ae is None


def test_merge_feed_last_write_wins_newest_first() -> None:
    first = rows_from_feed([_pair("tx-a", 10), _pair("tx-b", 9)])
    second = rows_from_feed([_pair("tx-a", 12, score=0.8, tier="BLOCK")])
    merged = merge_feed(first, second)
    assert [txn.transaction_id for txn, _ in merged] == ["tx-a", "tx-b"]
    assert merged[0][1].tier == RiskTier.BLOCK
    assert merged[0][1].score == 0.8


def test_http_source_keeps_buffer_on_failure(monkeypatch) -> None:
    source = HttpTransactionSource("http://127.0.0.1:9")
    source._buffer = rows_from_feed([_pair("tx-keep", 10)])

    def boom(*_args, **_kwargs):
        raise URLError("down")

    monkeypatch.setattr("dashboard.data_simulator.urlopen", boom)
    out = source.pull()
    assert source.last_error == "URLError"
    assert source.last_ok_at is None
    assert out[0][0].transaction_id == "tx-keep"


def test_http_source_empty_payload_clears_and_does_not_invent(monkeypatch) -> None:
    source = HttpTransactionSource("http://127.0.0.1:8000")
    source._buffer = rows_from_feed([_pair("tx-old", 10)])

    class _Resp:
        def read(self) -> bytes:
            return b"[]"

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr("dashboard.data_simulator.urlopen", lambda *_a, **_k: _Resp())
    out = source.pull()
    assert out == []
    assert source.last_error is None
    assert source.last_ok_at is not None


def test_rows_from_feed_nested_envelope() -> None:
    payload = {
        "source": "GET /transactions",
        "sandbox": True,
        "count": 1,
        "items": [
            {
                "payment": {
                    "id": "tx-nested",
                    "user_id": "aarav@senitenial",
                    "amount": 240.0,
                    "payee_vpa": "priya.p@oksbi",
                    "purpose": "dining",
                    "timestamp": "2026-09-28T10:00:00+00:00",
                    "location": {"status": "provided", "lat": 12.97, "lon": 77.59},
                },
                "canonical": {"decision": "REVIEW", "risk_score": 46, "scale": "0-100"},
                "policy": {
                    "action": "STEP_UP",
                    "legacy_tier": "STEP_UP",
                    "legacy_score": 0.46,
                    "scale": "0-1",
                    "action_required": True,
                },
                "models": {
                    "xgboost": {"available": True, "value": 0.9, "note": None},
                    "autoencoder": {"available": False, "value": None, "note": "component not wired"},
                    "graph": {"available": False, "value": None, "note": "component not wired"},
                    "structuring": {"available": False, "value": None, "note": "component not wired"},
                },
                "triggered_signals": [{"name": "NEW_MERCHANT", "value": 0.8}],
            }
        ],
    }
    pairs = rows_from_feed(payload)
    assert len(pairs) == 1
    txn, assessment = pairs[0]
    assert txn.transaction_id == "tx-nested"
    assert assessment.canonical_decision == "REVIEW"
    assert assessment.tier.value == "STEP_UP"
    assert assessment.score == 0.46
    assert assessment.p_ae is None
    assert assessment.ae_available is False
    assert assessment.contributions[0].name == "NEW_MERCHANT"


def test_http_source_empty_envelope_clears(monkeypatch) -> None:
    source = HttpTransactionSource("http://127.0.0.1:8000")
    source._buffer = rows_from_feed([_pair("tx-old", 10)])

    class _Resp:
        def read(self) -> bytes:
            return b'{"source":"GET /transactions","sandbox":true,"count":0,"items":[]}'

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr("dashboard.data_simulator.urlopen", lambda *_a, **_k: _Resp())
    out = source.pull()
    assert out == []
    assert source.last_error is None


def test_rows_from_feed_unavailable_and_unknown_model() -> None:
    payload = {
        "items": [
            {
                "payment": {
                    "id": "tx-unavail",
                    "user_id": "aarav@senitenial",
                    "amount": 240.0,
                    "payee_vpa": "priya.p@oksbi",
                    "timestamp": "2026-09-28T10:00:00+00:00",
                    "location": {"status": "omitted", "lat": None, "lon": None},
                },
                "canonical": {"decision": "REVIEW", "risk_score": 20},
                "policy": {
                    "action": "HOLD",
                    "legacy_tier": "HOLD",
                    "legacy_score": 0.2,
                    "action_required": True,
                },
                "models": {
                    "xgboost": {"available": False, "value": None, "note": "model unavailable"},
                    "autoencoder": {"available": False, "value": None},
                    "graph": {"available": False, "value": None},
                },
                "triggered_signals": [],
            },
            {
                "payment": {
                    "id": "tx-unknown",
                    "user_id": "aarav@senitenial",
                    "amount": 120.0,
                    "payee_vpa": "priya.p@oksbi",
                    "timestamp": "2026-09-28T09:00:00+00:00",
                    "location": {"status": "omitted", "lat": None, "lon": None},
                },
                "canonical": {"decision": "ALLOW", "risk_score": 8},
                "policy": {
                    "action": "ALLOW",
                    "legacy_tier": "ALLOW",
                    "legacy_score": 0.08,
                    "action_required": False,
                },
                "models": {
                    "xgboost": {"available": None, "value": None, "note": "model availability unknown"},
                    "autoencoder": {"available": False, "value": None},
                    "graph": {"available": False, "value": None},
                },
                "triggered_signals": [],
            },
        ]
    }
    pairs = rows_from_feed(payload)
    by_id = {txn.transaction_id: assessment for txn, assessment in pairs}
    assert by_id["tx-unavail"].ml_available is False
    assert by_id["tx-unavail"].p_xgb is None
    assert by_id["tx-unknown"].ml_available is None
    assert by_id["tx-unknown"].p_xgb is None


def test_rows_from_feed_skips_missing_score() -> None:
    payload = {
        "items": [
            {
                "payment": {
                    "id": "tx-noscore",
                    "user_id": "aarav@senitenial",
                    "amount": 240.0,
                    "payee_vpa": "priya.p@oksbi",
                    "timestamp": "2026-09-28T10:00:00+00:00",
                    "location": {"status": "omitted", "lat": None, "lon": None},
                },
                "canonical": {"decision": "ALLOW", "risk_score": 6},
                "policy": {"action": "ALLOW", "legacy_tier": "ALLOW"},
                "models": {"xgboost": {"available": False, "value": None}},
                "triggered_signals": [],
            }
        ]
    }
    assert rows_from_feed(payload) == []


def test_app_uses_http_source_only() -> None:
    text = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    assert "HttpTransactionSource" in text
    assert "SimulatedStream" not in text
