"""Persistence + short-lived counters.

SQLite is the default durable store (same schema works on Postgres later).
Velocity / rate-limit state stays in process — swap for Redis via REDIS_URL
when you have one. This file is not the source of truth for card data;
those fields are never accepted.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from risk.contracts import (
    BehaviorResult,
    DecisionResult,
    MlResult,
    NormalizedTransaction,
    RuleResult,
    SecuritySignals,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
_LOCK = threading.Lock()


def _db_path() -> Path:
    raw = os.getenv("SENTINALPAY_DATABASE_URL", "").strip()
    if raw.startswith("sqlite:///"):
        path = Path(raw[len("sqlite:///") :])
        return path if path.is_absolute() else REPO_ROOT / path
    return REPO_ROOT / "data" / "sentinalpay.db"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    first_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    amount REAL NOT NULL,
    currency TEXT NOT NULL,
    merchant_id TEXT,
    merchant_category TEXT,
    timestamp TEXT NOT NULL,
    device_id TEXT,
    ip_address TEXT,
    latitude REAL,
    longitude REAL
);
CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    PRIMARY KEY (device_id, user_id)
);
CREATE TABLE IF NOT EXISTS merchants (
    merchant_id TEXT PRIMARY KEY,
    category TEXT,
    txn_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS user_behavior_profiles (
    user_id TEXT PRIMARY KEY,
    avg_amount REAL,
    median_amount REAL,
    max_amount REAL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS risk_assessments (
    transaction_id TEXT PRIMARY KEY,
    risk_score INTEGER NOT NULL,
    decision TEXT NOT NULL,
    confidence REAL NOT NULL,
    fraud_probability REAL,
    model_version TEXT,
    rule_score INTEGER,
    behavioral_score INTEGER,
    security_score INTEGER,
    created_at TEXT NOT NULL,
    result_json TEXT
);
CREATE TABLE IF NOT EXISTS triggered_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id TEXT NOT NULL,
    rule TEXT NOT NULL,
    severity TEXT NOT NULL,
    score INTEGER NOT NULL,
    reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS review_cases (
    transaction_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    original_score INTEGER NOT NULL,
    risk_factors TEXT,
    reviewer_decision TEXT,
    reason TEXT,
    reviewed_at TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    risk_score INTEGER NOT NULL,
    decision TEXT NOT NULL,
    triggered_rules TEXT,
    behavioral_signals TEXT,
    ml_probability REAL,
    model_version TEXT,
    engine_version TEXT,
    processing_ms REAL
);
CREATE TABLE IF NOT EXISTS model_versions (
    version TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);
"""


class VelocityCache:
    """Redis-shaped counters. In-process unless REDIS_URL is set later."""

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def add(self, key: str, ts: float, window_s: float) -> int:
        bucket = self._events[key]
        cutoff = ts - window_s
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        bucket.append(ts)
        return len(bucket)

    def count(self, key: str, ts: float, window_s: float) -> int:
        bucket = self._events[key]
        cutoff = ts - window_s
        return sum(1 for item in bucket if item >= cutoff)


class RiskStore:
    def __init__(self, path: Path | None = None) -> None:
        self.cache = VelocityCache()
        self._path = path or _db_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            cols = {row[1] for row in conn.execute("PRAGMA table_info(risk_assessments)")}
            if "result_json" not in cols:
                conn.execute("ALTER TABLE risk_assessments ADD COLUMN result_json TEXT")
                conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def has_transaction(self, transaction_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM transactions WHERE transaction_id = ?",
                (transaction_id,),
            ).fetchone()
        return row is not None

    def get_assessment(self, transaction_id: str) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM risk_assessments WHERE transaction_id = ?",
                (transaction_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_result(self, transaction_id: str) -> Optional[dict[str, Any]]:
        row = self.get_assessment(transaction_id)
        if row is None:
            return None
        raw = row.get("result_json")
        if raw:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict):
                return payload
        return {
            "transaction_id": transaction_id,
            "risk_score": int(row["risk_score"]),
            "decision": row["decision"],
            "confidence": float(row["confidence"]),
        }

    def count_transactions(self, user_id: str | None = None) -> int:
        with self._connect() as conn:
            if user_id:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM transactions WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) AS n FROM transactions").fetchone()
        return int(row["n"]) if row else 0

    def count_audits(self, transaction_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM audit_logs WHERE transaction_id = ?",
                (transaction_id,),
            ).fetchone()
        return int(row["n"]) if row else 0

    def user_history(self, user_id: str, limit: int = 80) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT transaction_id, user_id, amount, merchant_id, timestamp,
                       latitude, longitude, device_id, ip_address, merchant_category
                FROM transactions
                WHERE user_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def device_users(self, device_id: str) -> int:
        if not device_id:
            return 0
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM devices WHERE device_id = ?",
                (device_id,),
            ).fetchone()
        return int(row["n"]) if row else 0

    def known_device(self, user_id: str, device_id: str) -> bool:
        if not device_id:
            return False
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM devices WHERE device_id = ? AND user_id = ?",
                (device_id, user_id),
            ).fetchone()
        return row is not None

    def recent_same_payload(
        self, user_id: str, amount: float, merchant_id: str, ts: datetime, window_s: float
    ) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT timestamp FROM transactions
                WHERE user_id = ? AND amount = ? AND merchant_id = ?
                ORDER BY timestamp DESC LIMIT 1
                """,
                (user_id, amount, merchant_id),
            ).fetchone()
        if not row:
            return False
        prior = datetime.fromisoformat(row["timestamp"])
        return abs((ts - prior).total_seconds()) <= window_s

    def persist(
        self,
        txn: NormalizedTransaction,
        security: SecuritySignals,
        rules: RuleResult,
        behavior: BehaviorResult,
        ml: MlResult,
        decision: DecisionResult,
        engine_version: str,
        processing_ms: float,
        result: dict[str, Any] | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        factors = json.dumps([{"factor": f.factor, "impact": f.impact} for f in decision.risk_factors])
        rules_json = json.dumps(
            [{"rule": r.rule, "severity": r.severity, "score": r.score, "reason": r.reason} for r in rules.triggered_rules]
        )
        anomalies_json = json.dumps(
            [{"feature": a.feature, "severity": a.severity, "deviation": a.deviation} for a in behavior.anomalies]
        )
        with _LOCK, self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users (user_id, first_seen) VALUES (?, ?)",
                (txn.user_id, now),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO transactions (
                    transaction_id, user_id, amount, currency, merchant_id,
                    merchant_category, timestamp, device_id, ip_address, latitude, longitude
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    txn.transaction_id,
                    txn.user_id,
                    txn.amount,
                    txn.currency,
                    txn.merchant_id,
                    txn.merchant_category,
                    txn.timestamp.isoformat(),
                    txn.device_id,
                    txn.ip_address,
                    txn.latitude,
                    txn.longitude,
                ),
            )
            if txn.device_id:
                conn.execute(
                    "INSERT OR IGNORE INTO devices (device_id, user_id, first_seen) VALUES (?, ?, ?)",
                    (txn.device_id, txn.user_id, now),
                )
            conn.execute(
                """
                INSERT INTO merchants (merchant_id, category, txn_count) VALUES (?, ?, 1)
                ON CONFLICT(merchant_id) DO UPDATE SET
                    txn_count = txn_count + 1,
                    category = excluded.category
                """,
                (txn.merchant_id, txn.merchant_category),
            )
            profile = behavior.baseline
            conn.execute(
                """
                INSERT INTO user_behavior_profiles (user_id, avg_amount, median_amount, max_amount, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    avg_amount = excluded.avg_amount,
                    median_amount = excluded.median_amount,
                    max_amount = excluded.max_amount,
                    updated_at = excluded.updated_at
                """,
                (
                    txn.user_id,
                    profile.get("avg_amount"),
                    profile.get("median_amount"),
                    profile.get("max_amount"),
                    now,
                ),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO risk_assessments (
                    transaction_id, risk_score, decision, confidence, fraud_probability,
                    model_version, rule_score, behavioral_score, security_score, created_at,
                    result_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    txn.transaction_id,
                    decision.risk_score,
                    decision.decision,
                    decision.confidence,
                    ml.fraud_probability,
                    ml.model_version,
                    rules.rule_score,
                    behavior.behavioral_score,
                    security.security_risk_score,
                    now,
                    json.dumps(result) if result is not None else None,
                ),
            )
            conn.execute("DELETE FROM triggered_rules WHERE transaction_id = ?", (txn.transaction_id,))
            for item in rules.triggered_rules:
                conn.execute(
                    """
                    INSERT INTO triggered_rules (transaction_id, rule, severity, score, reason)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (txn.transaction_id, item.rule, item.severity, item.score, item.reason),
                )
            if decision.decision == "REVIEW":
                conn.execute(
                    """
                    INSERT OR IGNORE INTO review_cases (
                        transaction_id, status, original_score, risk_factors, created_at
                    ) VALUES (?, 'PENDING', ?, ?, ?)
                    """,
                    (txn.transaction_id, decision.risk_score, factors, now),
                )
            conn.execute(
                """
                INSERT INTO audit_logs (
                    transaction_id, timestamp, risk_score, decision, triggered_rules,
                    behavioral_signals, ml_probability, model_version, engine_version, processing_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    txn.transaction_id,
                    now,
                    decision.risk_score,
                    decision.decision,
                    rules_json,
                    anomalies_json,
                    ml.fraud_probability,
                    ml.model_version,
                    engine_version,
                    processing_ms,
                ),
            )
            conn.execute(
                "INSERT OR IGNORE INTO model_versions (version, created_at) VALUES (?, ?)",
                (ml.model_version, now),
            )
            conn.commit()

    def submit_review(self, transaction_id: str, decision: str, reason: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        with _LOCK, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM review_cases WHERE transaction_id = ?",
                (transaction_id,),
            ).fetchone()
            if row is None:
                raise KeyError(transaction_id)
            conn.execute(
                """
                UPDATE review_cases
                SET status = ?, reviewer_decision = ?, reason = ?, reviewed_at = ?
                WHERE transaction_id = ?
                """,
                (decision, decision, reason, now, transaction_id),
            )
            conn.commit()
            updated = conn.execute(
                "SELECT * FROM review_cases WHERE transaction_id = ?",
                (transaction_id,),
            ).fetchone()
        return dict(updated)

    def recent_evaluations(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT t.transaction_id, t.user_id, t.amount, t.merchant_id, t.merchant_category,
                       t.timestamp, t.latitude, t.longitude, a.risk_score, a.decision,
                       a.fraud_probability, a.result_json
                FROM transactions t
                JOIN risk_assessments a ON a.transaction_id = t.transaction_id
                ORDER BY t.timestamp DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def pending_reviews(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM review_cases WHERE status = 'PENDING' ORDER BY created_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]


_STORE: RiskStore | None = None


def get_store() -> RiskStore:
    global _STORE
    if _STORE is None:
        _STORE = RiskStore()
    return _STORE


def reset_store() -> None:
    global _STORE
    _STORE = None
