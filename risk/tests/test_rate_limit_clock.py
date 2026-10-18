"""API rate limits use request time, not the payment timestamp."""

from pathlib import Path

from risk.config import RiskConfig
from risk.pipeline import evaluate_transaction
from risk.store import RiskStore


def test_historical_stamps_still_rate_limit(tmp_path: Path) -> None:
    store = RiskStore(tmp_path / "rl.db")
    cfg = RiskConfig()
    limited = []
    for i in range(cfg.rate_limit_per_min + 5):
        result = evaluate_transaction(
            {
                "transaction_id": f"rl-hist-{i}",
                "user_id": "USR_RL",
                "amount": 120,
                "merchant_id": "m@oksbi",
                    "timestamp": f"{2018 + (i % 8)}-06-01T00:00:00+00:00",
            },
            store=store,
            config=cfg,
            client_key="rl-client",
        )
        limited.append(result["security"]["rate_limited"])
    assert limited[0] is False
    assert any(limited)
