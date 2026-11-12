"""Isolate HTTP tests on a temp SQLite store."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from api.tests.desk_auth import DESK_PASSWORD, DESK_USER
from risk.store import get_store, reset_store


def seed_allow(transaction_id: str, amount: float = 10.0, user_id: str = "aarav@senitenial") -> None:
    """Store a primary ALLOW so an order endpoint can be tested without bypassing risk."""
    now = datetime.now(timezone.utc).isoformat()
    result = {
        "transaction_id": transaction_id,
        "user_id": user_id,
        "action": "ALLOW",
        "decision": "ALLOW",
        "risk_score": 1,
    }
    store = get_store()
    with store._connect() as conn:
        conn.execute(
            """
            INSERT INTO transactions (
                transaction_id, user_id, amount, currency, merchant_id, merchant_category, timestamp
            ) VALUES (?, ?, ?, 'INR', 'shop@upi', 'p2p', ?)
            """,
            (transaction_id, user_id, amount, now),
        )
        conn.execute(
            """
            INSERT INTO risk_assessments (
                transaction_id, risk_score, decision, confidence, fraud_probability,
                model_version, rule_score, behavioral_score, security_score, created_at, result_json
            ) VALUES (?, 1, 'ALLOW', 0.5, 0.01, 'test', 0, 0, 0, ?, ?)
            """,
            (transaction_id, now, json.dumps(result)),
        )
        conn.commit()


@pytest.fixture(autouse=True)
def isolated_risk_store(tmp_path, monkeypatch):
    monkeypatch.setenv("SENTINALPAY_DATABASE_URL", f"sqlite:///{(tmp_path / 'phase1.db').as_posix()}")
    monkeypatch.setenv("SENTINALPAY_HIGH_RISK_CATEGORIES", "gambling,crypto,jewelry")
    monkeypatch.setenv("SENTINALPAY_PBKDF2_ROUNDS", "2")
    monkeypatch.setenv("SENTINALPAY_REQUIRE_LOGIN", "0")
    monkeypatch.setenv("SENTINALPAY_API_KEY", "")
    monkeypatch.setenv("SENTINALPAY_ADMIN_USERNAME", DESK_USER)
    monkeypatch.setenv("SENTINALPAY_ADMIN_PASSWORD", DESK_PASSWORD)
    monkeypatch.setenv("SENTINALPAY_ARGON2_TIME", "1")
    monkeypatch.setenv("SENTINALPAY_ARGON2_MEMORY", "8")
    monkeypatch.setenv("SENTINALPAY_COOKIE_SECURE", "0")
    reset_store()
    yield
    reset_store()
