"""Phase 5: Redis velocity and optional Postgres."""

import os

import pytest

from risk.store import VelocityCache, database_kind


class _FakeRedis:
    def __init__(self) -> None:
        self.z = {}

    def zadd(self, name, mapping):
        bucket = self.z.setdefault(name, {})
        bucket.update(mapping)
        return 1

    def zremrangebyscore(self, name, lo, hi):
        bucket = self.z.get(name, {})
        low = float("-inf") if lo == "-inf" else float(lo)
        high = float(hi)
        for key, score in list(bucket.items()):
            if low <= float(score) <= high:
                del bucket[key]

    def zcount(self, name, lo, hi):
        bucket = self.z.get(name, {})
        return sum(1 for score in bucket.values() if float(lo) <= float(score) <= float(hi))


def test_database_kind() -> None:
    assert database_kind("sqlite:///data/x.db") == "sqlite"
    assert database_kind("postgresql://u:p@localhost/db") == "postgres"


def test_redis_velocity_does_not_count_old_events() -> None:
    cache = VelocityCache(redis_client=_FakeRedis())
    assert cache.add("user:a", 100.0, 10.0) == 1
    assert cache.add("user:a", 102.0, 10.0) == 2
    assert cache.add("user:a", 200.0, 10.0) == 1


@pytest.mark.skipif(not os.getenv("SENTINALPAY_TEST_POSTGRES"), reason="Postgres DSN not set")
def test_postgres_idempotency() -> None:
    from risk.config import RiskConfig
    from risk.pipeline import evaluate_transaction
    from risk.store import RiskStore

    store = RiskStore(dsn=os.environ["SENTINALPAY_TEST_POSTGRES"], seed_demo=False)
    payload = {
        "transaction_id": "TXN_PG_1",
        "user_id": "USR_PG",
        "amount": 500,
        "merchant_id": "m@oksbi",
        "timestamp": "2026-09-28T10:00:00+00:00",
    }
    first = evaluate_transaction(payload, store=store, config=RiskConfig())
    second = evaluate_transaction(payload, store=store, config=RiskConfig())
    assert second["risk_score"] == first["risk_score"]
    assert store.count_transactions("USR_PG") == 1
