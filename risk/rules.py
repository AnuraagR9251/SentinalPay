"""Independent rule functions. Enable/disable via config, not scattered ifs."""

from __future__ import annotations

from statistics import mean, pstdev
from typing import Callable, Sequence

from detection.features.location import haversine_km
from risk.config import RiskConfig
from risk.contracts import NormalizedTransaction, RuleResult, TriggeredRule

History = Sequence[dict]


def _zscore(amount: float, history: History) -> float | None:
    amounts = [float(row["amount"]) for row in history]
    if len(amounts) < 3:
        return None
    avg = mean(amounts)
    spread = pstdev(amounts) if len(amounts) > 1 else 0.0
    if spread == 0:
        return 0.0 if amount == avg else 8.0
    return (amount - avg) / spread


def rule_amount_anomaly(txn: NormalizedTransaction, history: History, config: RiskConfig) -> TriggeredRule | None:
    z = _zscore(txn.amount, history)
    if z is None or z < config.amount_z_flag:
        return None
    return TriggeredRule(
        rule="AMOUNT_ANOMALY",
        severity="HIGH" if z >= 5 else "MEDIUM",
        score=25 if z >= 5 else 15,
        reason=f"amount ₹{txn.amount:.0f} is {z:.1f}σ above this user's baseline",
    )


def rule_velocity(txn: NormalizedTransaction, history: History, config: RiskConfig) -> TriggeredRule | None:
    t = txn.timestamp
    last_5m = 1 + sum(1 for row in history if 0 <= (t - _ts(row)).total_seconds() <= 300)
    last_1h = 1 + sum(1 for row in history if 0 <= (t - _ts(row)).total_seconds() <= 3600)
    if last_5m >= config.velocity_5m_limit:
        return TriggeredRule(
            rule="HIGH_VELOCITY",
            severity="HIGH",
            score=20,
            reason=f"{last_5m} transactions detected within 5 minutes",
        )
    if last_1h >= config.velocity_1h_limit:
        return TriggeredRule(
            rule="HIGH_VELOCITY",
            severity="MEDIUM",
            score=12,
            reason=f"{last_1h} transactions detected within 1 hour",
        )
    return None


def rule_geo(txn: NormalizedTransaction, history: History, config: RiskConfig) -> TriggeredRule | None:
    if txn.latitude is None or txn.longitude is None or not history:
        return None
    prior = next((row for row in history if row.get("latitude") is not None), None)
    if prior is None:
        return None
    seconds = (txn.timestamp - _ts(prior)).total_seconds()
    if seconds <= 0:
        return None
    dist = haversine_km(float(prior["latitude"]), float(prior["longitude"]), txn.latitude, txn.longitude)
    kmh = dist / (seconds / 3600.0)
    if kmh < config.geo_speed_kmh:
        return None
    return TriggeredRule(
        rule="IMPOSSIBLE_TRAVEL",
        severity="HIGH",
        score=25,
        reason=f"{dist:.0f} km in {seconds:.0f}s implies {kmh:.0f} km/h",
    )


def rule_device(txn: NormalizedTransaction, history: History, config: RiskConfig) -> TriggeredRule | None:
    del config
    if not txn.device_id:
        return None
    seen = {row.get("device_id") for row in history if row.get("device_id")}
    if not seen:
        return TriggeredRule(
            rule="NEW_DEVICE",
            severity="MEDIUM",
            score=15,
            reason="Device has not previously been associated with this user",
        )
    if txn.device_id not in seen:
        return TriggeredRule(
            rule="NEW_DEVICE",
            severity="MEDIUM",
            score=15,
            reason="Device has not previously been associated with this user",
        )
    return None


def rule_merchant(txn: NormalizedTransaction, history: History, config: RiskConfig) -> TriggeredRule | None:
    # Category ≠ merchant fraud history. electronics is a feature, not a high-risk category.
    hits: list[TriggeredRule] = []
    if txn.merchant_category in config.high_risk_categories:
        hits.append(
            TriggeredRule(
                rule="HIGH_RISK_MERCHANT",
                severity="MEDIUM",
                score=12,
                reason=f"merchant category '{txn.merchant_category}' is high-risk",
            )
        )
    known = {row.get("merchant_id") for row in history}
    if history and txn.merchant_id not in known:
        hits.append(
            TriggeredRule(
                rule="NEW_MERCHANT",
                severity="LOW",
                score=8,
                reason="merchant is unusual for this user",
            )
        )
    if not hits:
        return None
    # One slot per rule function — keep the stronger hit.
    return max(hits, key=lambda item: item.score)


def rule_time(txn: NormalizedTransaction, history: History, config: RiskConfig) -> TriggeredRule | None:
    del config
    if len(history) < 5:
        return None
    hours = [_ts(row).hour for row in history]
    typical = {h for h in hours if hours.count(h) >= 2}
    if typical and txn.timestamp.hour not in typical and txn.timestamp.hour < 6:
        return TriggeredRule(
            rule="UNUSUAL_HOUR",
            severity="MEDIUM",
            score=10,
            reason=f"payment at {txn.timestamp.hour:02d}:00 is outside this user's usual hours",
        )
    return None


def rule_failed_attempts(txn: NormalizedTransaction, history: History, config: RiskConfig) -> TriggeredRule | None:
    del history, config
    if txn.recent_failures < 3:
        return None
    return TriggeredRule(
        rule="FAILED_ATTEMPTS",
        severity="HIGH",
        score=18,
        reason=f"{txn.recent_failures} failed attempts preceded this payment",
    )


def _ts(row: dict):
    from datetime import datetime

    raw = row["timestamp"]
    if isinstance(raw, datetime):
        return raw
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))


RULE_FNS: tuple[Callable[..., TriggeredRule | None], ...] = (
    rule_amount_anomaly,
    rule_velocity,
    rule_geo,
    rule_device,
    rule_merchant,
    rule_time,
    rule_failed_attempts,
)


def run_rules(txn: NormalizedTransaction, history: History, config: RiskConfig) -> RuleResult:
    triggered = [fn(txn, history, config) for fn in RULE_FNS]
    hits = tuple(item for item in triggered if item is not None)
    return RuleResult(rule_score=min(100, sum(item.score for item in hits)), triggered_rules=hits)
