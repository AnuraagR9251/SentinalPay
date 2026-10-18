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


class _PostgresConn:
    """psycopg connection with SQLite-style ? placeholders."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def execute(self, sql: str, params: tuple = ()) -> Any:
        adapted = (
            sql.replace("INSERT OR IGNORE INTO", "INSERT INTO")
            .replace("INSERT OR REPLACE INTO", "INSERT INTO")
            .replace("?", "%s")
        )
        if "INSERT INTO users " in adapted and "ON CONFLICT" not in adapted:
            adapted += " ON CONFLICT (user_id) DO NOTHING"
        elif "INSERT INTO transactions " in adapted and "ON CONFLICT" not in adapted:
            adapted += " ON CONFLICT (transaction_id) DO NOTHING"
        elif "INSERT INTO devices " in adapted and "ON CONFLICT" not in adapted:
            adapted += " ON CONFLICT (device_id, user_id) DO NOTHING"
        elif "INSERT INTO review_cases " in adapted and "ON CONFLICT" not in adapted:
            adapted += " ON CONFLICT (transaction_id) DO NOTHING"
        elif "INSERT INTO model_versions " in adapted and "ON CONFLICT" not in adapted:
            adapted += " ON CONFLICT (version) DO NOTHING"
        elif "INSERT INTO risk_assessments " in adapted and "ON CONFLICT" not in adapted:
            adapted += " ON CONFLICT (transaction_id) DO NOTHING"
        elif "INSERT INTO auth_accounts " in adapted and "ON CONFLICT" not in adapted:
            adapted += (
                " ON CONFLICT (user_id) DO UPDATE SET"
                " password_hash = EXCLUDED.password_hash, pin_hash = EXCLUDED.pin_hash,"
                " display_name = EXCLUDED.display_name"
            )
        elif "INSERT INTO sessions " in adapted and "ON CONFLICT" not in adapted:
            adapted += " ON CONFLICT (token) DO NOTHING"
        return self._conn.execute(adapted, params)

    def executescript(self, script: str) -> None:
        for stmt in script.split(";"):
            sql = stmt.strip()
            if sql:
                self._conn.execute(sql)

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "_PostgresConn":
        return self

    def __exit__(self, *exc: object) -> None:
        if exc[0] is None:
            self._conn.commit()
        self._conn.close()


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
CREATE TABLE IF NOT EXISTS auth_accounts (
    user_id TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    pin_hash TEXT NOT NULL,
    display_name TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

_PG_SCHEMA = _SCHEMA.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY")


def database_kind(url: str | None = None) -> str:
    raw = (url if url is not None else os.getenv("SENTINALPAY_DATABASE_URL", "")).strip().lower()
    if raw.startswith("postgres://") or raw.startswith("postgresql://"):
        return "postgres"
    return "sqlite"


class VelocityCache:
    """Redis-shaped counters. In-process unless REDIS_URL is set."""

    def __init__(self, redis_client: Any = None) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._redis = redis_client
        if self._redis is None:
            url = os.getenv("SENTINALPAY_REDIS_URL", "").strip()
            if url:
                try:
                    import redis

                    client = redis.Redis.from_url(url)
                    client.ping()
                    self._redis = client
                except Exception:
                    self._redis = None

    def add(self, key: str, ts: float, window_s: float) -> int:
        if self._redis is not None:
            name = f"sp:{key}"
            self._redis.zadd(name, {str(ts): ts})
            self._redis.zremrangebyscore(name, "-inf", ts - window_s)
            return int(self._redis.zcount(name, ts - window_s, ts))
        bucket = self._events[key]
        cutoff = ts - window_s
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        bucket.append(ts)
        return len(bucket)

    def count(self, key: str, ts: float, window_s: float) -> int:
        if self._redis is not None:
            return int(self._redis.zcount(f"sp:{key}", ts - window_s, ts))
        bucket = self._events[key]
        cutoff = ts - window_s
        return sum(1 for item in bucket if item >= cutoff)


class RiskStore:
    def __init__(self, path: Path | None = None, dsn: str | None = None, seed_demo: bool | None = None) -> None:
        self.cache = VelocityCache()
        self._dsn = (dsn or os.getenv("SENTINALPAY_DATABASE_URL", "")).strip()
        self._pg = database_kind(self._dsn) == "postgres"
        self._path = path or _db_path()
        if not self._pg:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            if self._pg:
                conn.executescript(_PG_SCHEMA) if hasattr(conn, "executescript") else self._exec_script(conn, _PG_SCHEMA)
            else:
                conn.executescript(_SCHEMA)
                cols = {row[1] for row in conn.execute("PRAGMA table_info(risk_assessments)")}
                if "result_json" not in cols:
                    conn.execute("ALTER TABLE risk_assessments ADD COLUMN result_json TEXT")
                    conn.commit()
        if seed_demo is None:
            seed_demo = path is None
        if seed_demo:
            self.ensure_demo_accounts()

    def _exec_script(self, conn: Any, script: str) -> None:
        for stmt in script.split(";"):
            sql = stmt.strip()
            if sql:
                conn.execute(sql)

    def _connect(self) -> Any:
        if self._pg:
            import psycopg
            from psycopg.rows import dict_row

            conn = psycopg.connect(self._dsn, row_factory=dict_row)
            return _PostgresConn(conn)
        conn = sqlite3.connect(self._path, check_same_thread=False, timeout=15)
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
    ) -> bool:
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
            claimed = conn.execute(
                """
                INSERT OR IGNORE INTO risk_assessments (
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
            if self._pg:
                inserted = int(getattr(claimed, "rowcount", 0) or 0)
            else:
                changes = conn.execute("SELECT changes() AS n").fetchone()
                inserted = int(changes["n"] if changes is not None else 0)
            if inserted <= 0:
                return False
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
        return True

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

    def ensure_demo_accounts(self) -> None:
        from risk.passwords import hash_secret

        seeds = (
            ("aarav@senitenial", "demo123", "1234", "Aarav Sharma"),
            ("priya@senitenial", "demo123", "1234", "Priya Mehra"),
            ("newbie@senitenial", "demo123", "1234", "New user"),
        )
        now = datetime.now(timezone.utc).isoformat()
        with _LOCK, self._connect() as conn:
            for user_id, password, pin, name in seeds:
                existing = conn.execute(
                    "SELECT 1 FROM auth_accounts WHERE user_id = ?", (user_id,)
                ).fetchone()
                if existing:
                    continue
                conn.execute(
                    "INSERT OR IGNORE INTO users (user_id, first_seen) VALUES (?, ?)",
                    (user_id, now),
                )
                conn.execute(
                    """
                    INSERT INTO auth_accounts (user_id, password_hash, pin_hash, display_name)
                    VALUES (?, ?, ?, ?)
                    """,
                    (user_id, hash_secret(password), hash_secret(pin), name),
                )
            conn.commit()

    def verify_login(self, user_id: str, password: str) -> bool:
        from risk.passwords import verify_secret

        with self._connect() as conn:
            row = conn.execute(
                "SELECT password_hash FROM auth_accounts WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return False
        stored = row["password_hash"] if not isinstance(row, tuple) else row[0]
        return verify_secret(password, stored)

    def verify_pin(self, user_id: str, pin: str) -> bool:
        from risk.passwords import verify_secret

        with self._connect() as conn:
            row = conn.execute(
                "SELECT pin_hash FROM auth_accounts WHERE user_id = ?",
                (user_id,),
            ).fetchone()
        if row is None:
            return False
        stored = row["pin_hash"] if not isinstance(row, tuple) else row[0]
        return verify_secret(pin, stored)

    def create_session(self, user_id: str) -> str:
        import secrets

        token = secrets.token_hex(24)
        now = datetime.now(timezone.utc).isoformat()
        with _LOCK, self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
                (token, user_id, now),
            )
            conn.commit()
        return token

    def session_user(self, token: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT user_id FROM sessions WHERE token = ?",
                (token,),
            ).fetchone()
        if row is None:
            return None
        return row["user_id"] if not isinstance(row, tuple) else row[0]

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
