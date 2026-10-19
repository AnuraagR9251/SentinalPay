"""Persistence + short-lived counters.

SQLite is the default durable store (same schema works on Postgres later).
Velocity / rate-limit state stays in process — swap for Redis via REDIS_URL
when you have one. This file is not the source of truth for card data;
those fields are never accepted.
"""

from __future__ import annotations

import hmac
import json
import os
import sqlite3
import threading
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
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


class StoreConflictError(ValueError):
    """transaction_id already claimed with different material fields."""


def payment_identity(user_id: Any, amount: Any, currency: Any, merchant_id: Any) -> tuple[str, str, str, str]:
    """Deterministic payment key. No PAN/PIN/credentials — identity fields only."""
    return (
        str(user_id or ""),
        f"{round(float(amount or 0), 2):.2f}",
        (str(currency or "INR").strip().upper() or "INR"),
        str(merchant_id or ""),
    )


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
        elif "INSERT INTO challenges " in adapted and "ON CONFLICT" not in adapted:
            adapted += " ON CONFLICT (challenge_id) DO NOTHING"
        elif "INSERT INTO payment_events " in adapted and "ON CONFLICT" not in adapted:
            adapted += " ON CONFLICT (event_id) DO NOTHING"
        elif "INSERT INTO provider_payments " in adapted and "ON CONFLICT" not in adapted:
            adapted += (
                " ON CONFLICT (payment_id) DO UPDATE SET"
                " status = EXCLUDED.status, amount = EXCLUDED.amount,"
                " currency = EXCLUDED.currency, order_id = EXCLUDED.order_id,"
                " latest_created_at = EXCLUDED.latest_created_at, updated_at = EXCLUDED.updated_at"
            )
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
    created_at TEXT NOT NULL,
    expires_at TEXT
);
CREATE TABLE IF NOT EXISTS payment_events (
    event_id TEXT PRIMARY KEY,
    payment_id TEXT,
    status TEXT NOT NULL,
    provider_created_at INTEGER NOT NULL DEFAULT 0,
    payload_hash TEXT NOT NULL,
    received_at TEXT NOT NULL,
    ignored INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS provider_payments (
    payment_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    amount REAL,
    currency TEXT,
    order_id TEXT,
    latest_created_at INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS challenges (
    challenge_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_token TEXT,
    transaction_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    consumed_at TEXT
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
        self._values: dict[str, deque[tuple[float, float]]] = defaultdict(deque)
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

    def add_value(self, key: str, ts: float, value: float, window_s: float) -> tuple[int, float]:
        """Count and sum amounts in the window. Concurrent callers share this cache."""
        import uuid

        if self._redis is not None:
            name = f"spv:{key}"
            member = f"{ts:.6f}:{float(value):.6f}:{uuid.uuid4().hex[:10]}"
            self._redis.zadd(name, {member: ts})
            self._redis.zremrangebyscore(name, "-inf", ts - window_s)
            items = self._redis.zrangebyscore(name, ts - window_s, ts)
            total = 0.0
            for item in items:
                text = item.decode() if isinstance(item, (bytes, bytearray)) else str(item)
                parts = text.split(":")
                if len(parts) >= 2:
                    total += float(parts[1])
            return len(items), total
        bucket = self._values[key]
        cutoff = ts - window_s
        while bucket and bucket[0][0] < cutoff:
            bucket.popleft()
        bucket.append((ts, float(value)))
        return len(bucket), sum(item[1] for item in bucket)


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
                self._ensure_sqlite_columns(conn)
        if seed_demo is None:
            seed_demo = path is None
        if seed_demo:
            self.ensure_demo_accounts()

    def _ensure_sqlite_columns(self, conn: Any) -> None:
        assessments = {row[1] for row in conn.execute("PRAGMA table_info(risk_assessments)")}
        if "result_json" not in assessments:
            conn.execute("ALTER TABLE risk_assessments ADD COLUMN result_json TEXT")
        sessions = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
        if "expires_at" not in sessions:
            conn.execute("ALTER TABLE sessions ADD COLUMN expires_at TEXT")
        conn.commit()

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

    def get_transaction(self, transaction_id: str) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM transactions WHERE transaction_id = ?",
                (transaction_id,),
            ).fetchone()
        return dict(row) if row else None

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

    def windowed_transactions(
        self, as_of: datetime, window_s: float, limit: int = 2000
    ) -> list[dict[str, Any]]:
        """Recent payments across users for the demo graph. Cap is a demo ceiling."""
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)
        else:
            as_of = as_of.astimezone(timezone.utc)
        start = (as_of - timedelta(seconds=float(window_s))).isoformat()
        end = as_of.isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT transaction_id, user_id, amount, merchant_id, timestamp, merchant_category
                FROM transactions
                WHERE timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp ASC
                LIMIT ?
                """,
                (start, end, int(limit)),
            ).fetchall()
        return [dict(row) for row in rows]

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
            existing = conn.execute(
                """
                SELECT user_id, amount, currency, merchant_id
                FROM transactions WHERE transaction_id = ?
                """,
                (txn.transaction_id,),
            ).fetchone()
            if existing is not None:
                prior = dict(existing)
                if payment_identity(
                    prior.get("user_id"),
                    prior.get("amount"),
                    prior.get("currency"),
                    prior.get("merchant_id"),
                ) != payment_identity(txn.user_id, txn.amount, txn.currency, txn.merchant_id):
                    raise StoreConflictError(
                        "transaction_id already used with different payment details"
                    )
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
        from datetime import timedelta

        from risk.passwords import hash_token

        token = secrets.token_hex(24)
        now = datetime.now(timezone.utc)
        ttl = int(os.getenv("SENTINALPAY_SESSION_TTL_SECONDS", "43200") or 43200)
        expires = (now + timedelta(seconds=max(1, ttl))).isoformat()
        with _LOCK, self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (hash_token(token), user_id, now.isoformat(), expires),
            )
            conn.commit()
        return token

    def session_user(self, token: str) -> str | None:
        from risk.passwords import hash_token

        if not token:
            return None
        digest = hash_token(token)
        now = datetime.now(timezone.utc)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT user_id, expires_at FROM sessions WHERE token = ?",
                (digest,),
            ).fetchone()
        if row is None:
            return None
        expires_raw = row["expires_at"] if not isinstance(row, tuple) else row[1]
        if expires_raw:
            expires = datetime.fromisoformat(str(expires_raw))
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if now > expires:
                return None
        return row["user_id"] if not isinstance(row, tuple) else row[0]

    def revoke_session(self, token: str) -> bool:
        from risk.passwords import hash_token

        if not token:
            return False
        digest = hash_token(token)
        with _LOCK, self._connect() as conn:
            cur = conn.execute("DELETE FROM sessions WHERE token = ?", (digest,))
            conn.commit()
            return int(cur.rowcount or 0) > 0

    def revoke_sessions(self, user_id: str) -> None:
        with _LOCK, self._connect() as conn:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            conn.commit()

    def record_login_failure(self, key: str) -> int:
        return self.cache.add(f"loginfail:{key}", datetime.now(timezone.utc).timestamp(), 300.0)

    def update_result_json(self, transaction_id: str, result: dict[str, Any]) -> None:
        with _LOCK, self._connect() as conn:
            conn.execute(
                "UPDATE risk_assessments SET result_json = ? WHERE transaction_id = ?",
                (json.dumps(result), transaction_id),
            )
            conn.commit()

    def create_challenge(
        self,
        user_id: str,
        transaction_id: str,
        session_token: str | None,
        *,
        ttl_seconds: int = 300,
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        import secrets
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        with _LOCK, self._connect() as conn:
            existing = conn.execute(
                """
                SELECT * FROM challenges
                WHERE transaction_id = ? AND consumed_at IS NULL AND expires_at > ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (transaction_id, now.isoformat()),
            ).fetchone()
            if existing:
                return dict(existing)
            from risk.passwords import hash_token

            challenge_id = secrets.token_hex(16)
            expires = (now + timedelta(seconds=ttl_seconds)).isoformat()
            session_ref = hash_token(session_token) if session_token else None
            conn.execute(
                """
                INSERT INTO challenges (
                    challenge_id, user_id, session_token, transaction_id,
                    created_at, expires_at, attempts, max_attempts, consumed_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, NULL)
                """,
                (challenge_id, user_id, session_ref, transaction_id, now.isoformat(), expires, max_attempts),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM challenges WHERE challenge_id = ?",
                (challenge_id,),
            ).fetchone()
        return dict(row)

    def get_challenge(self, challenge_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM challenges WHERE challenge_id = ?",
                (challenge_id,),
            ).fetchone()
        return dict(row) if row else None

    def verify_challenge(
        self,
        challenge_id: str,
        *,
        user_id: str,
        session_token: str | None,
        pin: str,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        with _LOCK, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM challenges WHERE challenge_id = ?",
                (challenge_id,),
            ).fetchone()
            if row is None:
                return {"ok": False, "error": "unknown_challenge"}
            data = dict(row)
            if data["user_id"] != user_id:
                return {"ok": False, "error": "user_mismatch"}
            stored_session = data.get("session_token")
            if stored_session:
                from risk.passwords import hash_token

                presented = hash_token(session_token) if session_token else ""
                if not session_token or not hmac.compare_digest(str(stored_session), presented):
                    return {"ok": False, "error": "session_mismatch"}
            if data.get("consumed_at"):
                return {"ok": False, "error": "replay"}
            expires = datetime.fromisoformat(str(data["expires_at"]))
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if now > expires:
                return {"ok": False, "error": "expired"}
            attempts = int(data["attempts"]) + 1
            max_attempts = int(data["max_attempts"])
            conn.execute(
                "UPDATE challenges SET attempts = ? WHERE challenge_id = ?",
                (attempts, challenge_id),
            )
            if attempts > max_attempts:
                conn.commit()
                return {"ok": False, "error": "locked"}
            from risk.passwords import verify_secret

            pin_row = conn.execute(
                "SELECT pin_hash FROM auth_accounts WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            stored_pin = None if pin_row is None else (pin_row["pin_hash"] if not isinstance(pin_row, tuple) else pin_row[0])
            if stored_pin is None or not verify_secret(pin, stored_pin):
                conn.commit()
                return {"ok": False, "error": "invalid_pin"}
            conn.execute(
                "UPDATE challenges SET consumed_at = ? WHERE challenge_id = ?",
                (now.isoformat(), challenge_id),
            )
            conn.commit()
        scored = self.get_result(data["transaction_id"]) or {}
        if str(scored.get("action") or "") != "STEP_UP":
            return {"ok": False, "error": "transaction_mismatch"}
        return {
            "ok": True,
            "transaction_id": data["transaction_id"],
            "sandbox": True,
            "note": "Sandbox PIN confirmation, not bank OTP",
        }

    def get_payment_event(self, event_id: str) -> dict[str, Any] | None:
        if not event_id:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM payment_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        return dict(row) if row else None

    def insert_payment_event(
        self,
        *,
        event_id: str,
        payment_id: str,
        status: str,
        provider_created_at: int,
        payload_hash: str,
        ignored: bool = False,
    ) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with _LOCK, self._connect() as conn:
            claimed = conn.execute(
                """
                INSERT OR IGNORE INTO payment_events (
                    event_id, payment_id, status, provider_created_at, payload_hash, received_at, ignored
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (event_id, payment_id, status, int(provider_created_at), payload_hash, now, 1 if ignored else 0),
            )
            if self._pg:
                inserted = int(getattr(claimed, "rowcount", 0) or 0)
            else:
                changes = conn.execute("SELECT changes() AS n").fetchone()
                inserted = int(changes["n"] if changes is not None else 0)
            conn.commit()
        return inserted > 0

    def claim_payment_event(
        self,
        *,
        event_id: str,
        payment_id: str,
        status: str,
        provider_created_at: int,
        payload_hash: str,
        amount: float,
        currency: str,
        order_id: str | None,
    ) -> dict[str, Any]:
        """Atomically claim a provider event and apply payment state if it is newest."""
        now = datetime.now(timezone.utc).isoformat()
        created = int(provider_created_at)
        with _LOCK, self._connect() as conn:
            claimed = conn.execute(
                """
                INSERT OR IGNORE INTO payment_events (
                    event_id, payment_id, status, provider_created_at, payload_hash, received_at, ignored
                ) VALUES (?, ?, ?, ?, ?, ?, 0)
                """,
                (event_id, payment_id, status, created, payload_hash, now),
            )
            if self._pg:
                inserted = int(getattr(claimed, "rowcount", 0) or 0)
            else:
                changes = conn.execute("SELECT changes() AS n").fetchone()
                inserted = int(changes["n"] if changes is not None else 0)
            if inserted <= 0:
                row = conn.execute(
                    "SELECT * FROM payment_events WHERE event_id = ?",
                    (event_id,),
                ).fetchone()
                conn.commit()
                prior = dict(row) if row else {}
                return {
                    "duplicate": True,
                    "out_of_order": False,
                    "status": prior.get("status"),
                    "event_id": event_id,
                }
            latest = 0
            current: dict[str, Any] = {}
            if payment_id:
                pay = conn.execute(
                    "SELECT * FROM provider_payments WHERE payment_id = ?",
                    (payment_id,),
                ).fetchone()
                if pay is not None:
                    current = dict(pay)
                    latest = int(current.get("latest_created_at") or 0)
            if payment_id and created < latest:
                conn.execute(
                    "UPDATE payment_events SET ignored = 1 WHERE event_id = ?",
                    (event_id,),
                )
                conn.commit()
                return {
                    "duplicate": False,
                    "out_of_order": True,
                    "status": current.get("status") or "unknown",
                    "event_id": event_id,
                }
            if payment_id:
                conn.execute(
                    """
                    INSERT INTO provider_payments (
                        payment_id, status, amount, currency, order_id, latest_created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(payment_id) DO UPDATE SET
                        status = excluded.status,
                        amount = excluded.amount,
                        currency = excluded.currency,
                        order_id = excluded.order_id,
                        latest_created_at = excluded.latest_created_at,
                        updated_at = excluded.updated_at
                    """,
                    (payment_id, status, amount, currency, order_id, created, now),
                )
            conn.commit()
            return {
                "duplicate": False,
                "out_of_order": False,
                "applied": True,
                "status": status,
                "event_id": event_id,
            }

    def latest_payment_created(self, payment_id: str) -> int:
        if not payment_id:
            return 0
        with self._connect() as conn:
            row = conn.execute(
                "SELECT latest_created_at FROM provider_payments WHERE payment_id = ?",
                (payment_id,),
            ).fetchone()
        if row is None:
            return 0
        return int(row["latest_created_at"] if not isinstance(row, tuple) else row[0] or 0)

    def upsert_provider_payment(
        self,
        *,
        payment_id: str,
        status: str,
        amount: float,
        currency: str,
        order_id: str | None,
        latest_created_at: int,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with _LOCK, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO provider_payments (
                    payment_id, status, amount, currency, order_id, latest_created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(payment_id) DO UPDATE SET
                    status = excluded.status,
                    amount = excluded.amount,
                    currency = excluded.currency,
                    order_id = excluded.order_id,
                    latest_created_at = excluded.latest_created_at,
                    updated_at = excluded.updated_at
                """,
                (payment_id, status, amount, currency, order_id, int(latest_created_at), now),
            )
            conn.commit()

    def get_provider_payment(self, payment_id: str) -> dict[str, Any] | None:
        if not payment_id:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM provider_payments WHERE payment_id = ?",
                (payment_id,),
            ).fetchone()
        return dict(row) if row else None

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
