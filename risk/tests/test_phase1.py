"""Phase 1 unification: one store, no Pune home, electronics is not fraud."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from risk.config import RiskConfig
from risk.pipeline import evaluate_transaction
from risk.store import RiskStore


def _cfg() -> RiskConfig:
    return RiskConfig()


def test_electronics_is_not_automatic_fraud(tmp_path: Path) -> None:
    store = RiskStore(tmp_path / "electronics.db")
    result = evaluate_transaction(
        {
            "transaction_id": "TXN_ELEC_1",
            "user_id": "USR_ELEC",
            "amount": 2200,
            "merchant_id": "croma.blr@oksbi",
            "merchant_category": "electronics",
            "timestamp": datetime(2026, 9, 28, 11, 0, tzinfo=timezone.utc).isoformat(),
            "latitude": 12.9716,
            "longitude": 77.5946,
        },
        store=store,
        config=_cfg(),
    )
    names = {item["rule"] for item in result["rules"]["triggered_rules"]}
    assert "HIGH_RISK_MERCHANT" not in names
    assert result["decision"] in {"ALLOW", "REVIEW", "BLOCK"}


def test_unknown_location_is_not_fraud(tmp_path: Path) -> None:
    store = RiskStore(tmp_path / "unknown-geo.db")
    result = evaluate_transaction(
        {
            "transaction_id": "TXN_GEO_1",
            "user_id": "USR_NEW",
            "amount": 350,
            "merchant_id": "kirana.del@oksbi",
            "merchant_category": "groceries",
            "timestamp": datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc).isoformat(),
            "latitude": 28.6139,
            "longitude": 77.2090,
        },
        store=store,
        config=_cfg(),
    )
    assert result["location_baseline"] == "UNKNOWN"
    names = {item["rule"] for item in result["rules"]["triggered_rules"]}
    assert "IMPOSSIBLE_TRAVEL" not in names
    factors = " ".join(item["factor"] for item in result["risk_factors"]).lower()
    assert "pune" not in factors


def test_no_universal_pune_home(tmp_path: Path) -> None:
    store = RiskStore(tmp_path / "cities.db")
    now = datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc)
    blr = {"latitude": 12.9716, "longitude": 77.5946}
    evaluate_transaction(
        {
            "transaction_id": "TXN_BLR_1",
            "user_id": "USR_BLR",
            "amount": 300,
            "merchant_id": "cafe.blr@oksbi",
            "timestamp": now.isoformat(),
            **blr,
        },
        store=store,
        config=_cfg(),
    )
    evaluate_transaction(
        {
            "transaction_id": "TXN_BLR_2",
            "user_id": "USR_BLR",
            "amount": 310,
            "merchant_id": "cafe.blr@oksbi",
            "timestamp": (now + timedelta(days=1)).isoformat(),
            **blr,
        },
        store=store,
        config=_cfg(),
    )
    third = evaluate_transaction(
        {
            "transaction_id": "TXN_BLR_3",
            "user_id": "USR_BLR",
            "amount": 320,
            "merchant_id": "cafe.blr@oksbi",
            "timestamp": (now + timedelta(days=2)).isoformat(),
            **blr,
        },
        store=store,
        config=_cfg(),
    )
    assert third["location_baseline"] == "KNOWN_NORMAL_LOCATION"
    names = {item["rule"] for item in third["rules"]["triggered_rules"]}
    assert "IMPOSSIBLE_TRAVEL" not in names

    delhi = evaluate_transaction(
        {
            "transaction_id": "TXN_DEL_1",
            "user_id": "USR_DEL",
            "amount": 280,
            "merchant_id": "cafe.del@oksbi",
            "timestamp": now.isoformat(),
            "latitude": 28.6139,
            "longitude": 77.2090,
        },
        store=store,
        config=_cfg(),
    )
    assert delhi["location_baseline"] == "UNKNOWN"
    blob = str(third) + str(delhi)
    assert "18.5204" not in blob
    assert "Pune" not in blob


def test_idempotent_evaluate_does_not_duplicate(tmp_path: Path) -> None:
    store = RiskStore(tmp_path / "idem.db")
    payload = {
        "transaction_id": "TXN_10001",
        "user_id": "USR_IDEM",
        "amount": 8500,
        "merchant_id": "MERCHANT_456",
        "merchant_category": "electronics",
        "timestamp": datetime(2026, 9, 28, 10, 30, tzinfo=timezone.utc).isoformat(),
        "latitude": 12.9716,
        "longitude": 77.5946,
    }
    first = evaluate_transaction(payload, store=store, config=_cfg())
    second = evaluate_transaction(payload, store=store, config=_cfg())
    assert second["risk_score"] == first["risk_score"]
    assert second["decision"] == first["decision"]
    assert second.get("idempotent") is True
    assert store.count_transactions("USR_IDEM") == 1
    assert store.count_audits("TXN_10001") == 1
