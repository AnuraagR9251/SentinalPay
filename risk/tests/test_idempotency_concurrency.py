"""Same transaction_id is claimed once at persist, even under threads."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from risk.config import RiskConfig
from risk.pipeline import evaluate_transaction
from risk.store import RiskStore


def test_concurrent_same_id_writes_one_audit(tmp_path: Path) -> None:
    store = RiskStore(tmp_path / "conc.db")
    payload = {
        "transaction_id": "TXN_RACE_1",
        "user_id": "USR_RACE",
        "amount": 900,
        "merchant_id": "shop@oksbi",
        "merchant_category": "dining",
        "timestamp": datetime(2026, 9, 28, 11, 0, tzinfo=timezone.utc).isoformat(),
        "latitude": 12.9716,
        "longitude": 77.5946,
        "device_id": "dev-race",
    }

    def _run() -> dict:
        return evaluate_transaction(payload, store=store, config=RiskConfig())

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(_run) for _ in range(8)]
        results = [fut.result() for fut in as_completed(futs)]

    scores = {item["risk_score"] for item in results}
    decisions = {item["decision"] for item in results}
    assert len(scores) == 1
    assert len(decisions) == 1
    assert store.count_transactions("USR_RACE") == 1
    assert store.count_audits("TXN_RACE_1") == 1
