"""Lab scenarios hit the real pipeline. Isolated users, synthetic history only."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from risk.config import RiskConfig
from risk.pipeline import evaluate_transaction
from risk.store import RiskStore

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
BLR = (12.9716, 77.5946)
DEL = (28.6139, 77.2090)
HOME_DEV = "lab-dev-home"
KIRANA = "kirana.lab@oksbi"


def _store(tmp_path: Path) -> RiskStore:
    return RiskStore(tmp_path / "lab.db")


def _eval(store: RiskStore, *, tid: str, user: str, amount: float, merchant: str, ts: datetime, device: str = HOME_DEV, geo=BLR, category: str = "groceries"):
    raw = {
        "transaction_id": tid,
        "user_id": user,
        "amount": amount,
        "merchant_id": merchant,
        "merchant_category": category,
        "timestamp": ts.isoformat(),
        "device_id": device,
    }
    if geo is not None:
        raw["latitude"], raw["longitude"] = geo
    return evaluate_transaction(raw, store=store, config=RiskConfig())


def _names(result: dict) -> set[str]:
    return {item["rule"] for item in result["rules"]["triggered_rules"]}


def _seed(store: RiskStore, rows: list[dict]) -> list[dict]:
    return [_eval(store, **row) for row in rows]


def test_grocery_known_payee_does_not_fire_suspicion_rules(tmp_path: Path) -> None:
    store = _store(tmp_path)
    user = "lab.grocery.t1@sentinal.sim"
    days = [14, 11, 8, 5, 2]
    amounts = [220, 180, 260, 200, 240]
    _seed(
        store,
        [
            {
                "tid": f"lab-grocery-h{i}-t1",
                "user": user,
                "amount": amounts[i],
                "merchant": KIRANA,
                "ts": NOW - timedelta(days=day),
            }
            for i, day in enumerate(days)
        ],
    )
    live = _eval(store, tid="lab-grocery-live-t1", user=user, amount=240, merchant=KIRANA, ts=NOW)
    names = _names(live)
    assert "HIGH_VELOCITY" not in names
    assert "IMPOSSIBLE_TRAVEL" not in names
    assert "AMOUNT_ANOMALY" not in names
    assert "NEW_MERCHANT" not in names
    assert "NEW_DEVICE" not in names
    assert live["experimental"]["note"].startswith("experimental")


def test_velocity_five_in_five_minutes(tmp_path: Path) -> None:
    store = _store(tmp_path)
    user = "lab.velocity.t1@sentinal.sim"
    for i, sec in enumerate((180, 120, 60, 30)):
        _eval(
            store,
            tid=f"lab-vel-h{i}-t1",
            user=user,
            amount=400,
            merchant=f"burst{i}.lab@oksbi",
            ts=NOW - timedelta(seconds=sec),
            category="p2p_transfer",
        )
    live = _eval(store, tid="lab-vel-live-t1", user=user, amount=400, merchant="burst-live.lab@oksbi", ts=NOW, category="p2p_transfer")
    assert "HIGH_VELOCITY" in _names(live)


def test_new_device_and_unusual_location(tmp_path: Path) -> None:
    store = _store(tmp_path)
    user = "lab.location_device.t1@sentinal.sim"
    for i, delta in enumerate((timedelta(days=3), timedelta(days=2), timedelta(seconds=120))):
        _eval(store, tid=f"lab-geo-h{i}-t1", user=user, amount=300, merchant=KIRANA, ts=NOW - delta)
    live = _eval(
        store,
        tid="lab-geo-live-t1",
        user=user,
        amount=900,
        merchant="delhi.lab@oksbi",
        ts=NOW,
        device="lab-dev-new",
        geo=DEL,
        category="p2p_transfer",
    )
    names = _names(live)
    assert "IMPOSSIBLE_TRAVEL" in names
    assert "NEW_DEVICE" in names
    assert live["location_baseline"] == "KNOWN_UNUSUAL_LOCATION"


def test_below_threshold_sets_experimental_structuring_not_a_canonical_rule(tmp_path: Path) -> None:
    store = _store(tmp_path)
    user = "lab.below_threshold.t1@sentinal.sim"
    unit = 16666
    for i, minutes in enumerate((75, 50, 25)):
        _eval(
            store,
            tid=f"lab-smurf-h{i}-t1",
            user=user,
            amount=unit,
            merchant=f"split{i}.lab@oksbi",
            ts=NOW - timedelta(minutes=minutes),
            category="p2p_transfer",
        )
    live = _eval(
        store,
        tid="lab-smurf-live-t1",
        user=user,
        amount=unit,
        merchant="split-live.lab@oksbi",
        ts=NOW,
        category="p2p_transfer",
    )
    assert "HIGH_VELOCITY" not in _names(live)
    assert live["experimental"]["structuring_flag"] is True
    assert "structuring" not in {name.lower() for name in _names(live)}
    assert "not blended" in live["experimental"]["note"]


def test_new_payee_above_baseline(tmp_path: Path) -> None:
    store = _store(tmp_path)
    user = "lab.new_payee.t1@sentinal.sim"
    for i, day in enumerate((10, 8, 6, 4, 2)):
        _eval(store, tid=f"lab-base-h{i}-t1", user=user, amount=200, merchant=KIRANA, ts=NOW - timedelta(days=day))
    live = _eval(
        store,
        tid="lab-new-live-t1",
        user=user,
        amount=8000,
        merchant="stranger.t1@oksbi",
        ts=NOW,
        category="p2p_transfer",
    )
    names = _names(live)
    assert "NEW_MERCHANT" in names
    assert "AMOUNT_ANOMALY" in names


def test_missing_location_skips_travel(tmp_path: Path) -> None:
    store = _store(tmp_path)
    user = "lab.missing_location.t1@sentinal.sim"
    for i, day in enumerate((3, 2, 1)):
        _eval(store, tid=f"lab-nogeo-h{i}-t1", user=user, amount=210, merchant=KIRANA, ts=NOW - timedelta(days=day), geo=None)
    live = _eval(store, tid="lab-nogeo-live-t1", user=user, amount=210, merchant=KIRANA, ts=NOW, geo=None)
    assert "IMPOSSIBLE_TRAVEL" not in _names(live)
    assert live["location_baseline"] == "UNKNOWN"


def test_thin_history_skips_amount_anomaly(tmp_path: Path) -> None:
    store = _store(tmp_path)
    user = "lab.thin_history.t1@sentinal.sim"
    _eval(store, tid="lab-thin-h0-t1", user=user, amount=200, merchant=KIRANA, ts=NOW - timedelta(days=1))
    live = _eval(
        store,
        tid="lab-thin-live-t1",
        user=user,
        amount=9000,
        merchant="newthin.t1@oksbi",
        ts=NOW,
        category="p2p_transfer",
    )
    assert "AMOUNT_ANOMALY" not in _names(live)
    assert "NEW_MERCHANT" in _names(live)


def test_replay_returns_stored_result(tmp_path: Path) -> None:
    store = _store(tmp_path)
    user = "lab.replay.t1@sentinal.sim"
    _eval(store, tid="lab-rep-h0-t1", user=user, amount=220, merchant=KIRANA, ts=NOW - timedelta(days=1))
    first = _eval(store, tid="lab-rep-live-t1", user=user, amount=220, merchant=KIRANA, ts=NOW)
    again = _eval(store, tid="lab-rep-live-t1", user=user, amount=220, merchant=KIRANA, ts=NOW)
    assert again.get("idempotent") is True
    assert again["decision"] == first["decision"]
    assert again["risk_score"] == first["risk_score"]


def test_legitimate_high_frequency_under_velocity_limit(tmp_path: Path) -> None:
    store = _store(tmp_path)
    user = "lab.legit_high_freq.t1@sentinal.sim"
    for i, sec in enumerate((90, 40)):
        _eval(store, tid=f"lab-freq-h{i}-t1", user=user, amount=180, merchant=KIRANA, ts=NOW - timedelta(seconds=sec))
    live = _eval(store, tid="lab-freq-live-t1", user=user, amount=180, merchant=KIRANA, ts=NOW)
    assert "HIGH_VELOCITY" not in _names(live)
