"""Pre-analysis security signals. Does not decide ALLOW/REVIEW/BLOCK."""

from __future__ import annotations

from datetime import datetime, timezone

from risk.config import RiskConfig
from risk.contracts import NormalizedTransaction, SecuritySignals
from risk.store import RiskStore


def inspect_security(
    txn: NormalizedTransaction,
    store: RiskStore,
    config: RiskConfig,
    *,
    client_key: str,
) -> SecuritySignals:
    notes: list[str] = []
    duplicate = store.has_transaction(txn.transaction_id)
    if duplicate:
        notes.append("duplicate transaction_id")

    now = datetime.now(timezone.utc)
    future = (txn.timestamp - now).total_seconds() > 5 * 60
    ancient = (now - txn.timestamp).total_seconds() > 10 * 365 * 24 * 3600
    invalid = future or ancient or txn.amount <= 0
    if future:
        notes.append("timestamp in the future")
    if ancient:
        notes.append("timestamp implausibly old")

    replay = store.recent_same_payload(
        txn.user_id, txn.amount, txn.merchant_id, txn.timestamp, config.replay_seconds
    )
    if replay:
        notes.append("possible replay of a recent payment")

    request_ts = now.timestamp()
    event_ts = txn.timestamp.timestamp()
    per_min = store.cache.add(f"rl:{client_key}", request_ts, 60.0)
    rate_limited = per_min > config.rate_limit_per_min
    if rate_limited:
        notes.append("excessive request rate")

    store.cache.add(f"user:{txn.user_id}:tx:5m", event_ts, 300.0)
    store.cache.add(f"user:{txn.user_id}:tx:1h", event_ts, 3600.0)
    count_5m, sum_5m = store.cache.add_value(f"user:{txn.user_id}:val:5m", event_ts, txn.amount, 300.0)
    store.cache.add_value(f"user:{txn.user_id}:val:1h", event_ts, txn.amount, 3600.0)
    high_spend = count_5m >= 3 and sum_5m >= 100000
    if high_spend:
        notes.append("high 5-minute spend velocity")
    if txn.device_id:
        store.cache.add(f"device:{txn.device_id}:activity", event_ts, 3600.0)
        users = store.device_users(txn.device_id)
        if users >= config.device_user_cap and not store.known_device(txn.user_id, txn.device_id):
            notes.append("device linked to many users")
            invalid = True

    score = 0
    if duplicate:
        score += 25
    if replay:
        score += 20
    if invalid:
        score += 20
    if rate_limited:
        score += 15
    if any("device linked" in note for note in notes):
        score += 15
    if high_spend:
        score += 10
    return SecuritySignals(
        duplicate_transaction=duplicate,
        replay_detected=replay,
        invalid_request=invalid,
        rate_limited=rate_limited,
        security_risk_score=min(100, score),
        notes=tuple(notes),
    )
