"""Payment velocity stays in the pipeline; HTTP 429 is a separate gate."""

from pathlib import Path

from risk.config import RiskConfig
from risk.pipeline import evaluate_transaction
from risk.store import RiskStore


def test_pipeline_does_not_http_rate_limit_on_historical_stamps(tmp_path: Path) -> None:
    store = RiskStore(tmp_path / "rl.db")
    cfg = RiskConfig()
    for i in range(3):
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
        assert result["security"]["rate_limited"] is False
        assert result["decision"] in {"ALLOW", "REVIEW", "BLOCK"}
