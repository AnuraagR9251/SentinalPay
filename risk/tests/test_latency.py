"""In-process risk evaluation latency. Excludes HTTP and Razorpay.

Workload: 1 warmup + 25 sequential evaluate_transaction calls on a temp SQLite
store. Do not treat a pass as p95 < 100 ms unless the printed numbers show it.
"""

from datetime import datetime, timezone
from pathlib import Path
from statistics import median

from risk.config import RiskConfig
from risk.pipeline import evaluate_transaction
from risk.store import RiskStore


def test_evaluate_latency_local_workload(tmp_path: Path) -> None:
    store = RiskStore(tmp_path / "lat.db")
    cfg = RiskConfig()
    samples: list[float] = []
    for i in range(26):
        result = evaluate_transaction(
            {
                "transaction_id": f"lat-{i}",
                "user_id": "USR_LAT",
                "amount": 240 + i,
                "merchant_id": "kirana@oksbi",
                "merchant_category": "groceries",
                "timestamp": datetime(2026, 9, 28, 11, 0, tzinfo=timezone.utc).isoformat(),
                "device_id": "dev-lat",
            },
            store=store,
            config=cfg,
        )
        samples.append(float(result["inference_latency_ms"]))
    timed = samples[1:]
    timed.sort()
    p50 = median(timed)
    p95 = timed[int(0.95 * (len(timed) - 1))]
    print(f"evaluate_transaction local N=25 p50={p50:.1f}ms p95={p95:.1f}ms (excludes HTTP/Razorpay)")
    assert p95 < 5000.0
    if p95 < 100.0:
        print("p95 is under the 100ms engineering target on this machine")
