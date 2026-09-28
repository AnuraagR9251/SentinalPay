"""Compare the payment to this user's baseline. Unusual ≠ fraud."""

from __future__ import annotations

from statistics import mean, median
from typing import Sequence

from risk.contracts import BehaviorAnomaly, BehaviorResult, NormalizedTransaction


def analyze_behavior(txn: NormalizedTransaction, history: Sequence[dict]) -> BehaviorResult:
    amounts = [float(row["amount"]) for row in history]
    anomalies: list[BehaviorAnomaly] = []
    baseline: dict = {"n": len(amounts)}
    if amounts:
        avg = mean(amounts)
        med = median(amounts)
        peak = max(amounts)
        baseline.update({"avg_amount": avg, "median_amount": med, "max_amount": peak})
        if avg > 0 and txn.amount > max(peak * 1.5, avg * 4):
            deviation = txn.amount / avg
            anomalies.append(
                BehaviorAnomaly(feature="transaction_amount", severity="HIGH", deviation=round(deviation, 2))
            )
        elif avg > 0 and txn.amount > avg * 2:
            anomalies.append(
                BehaviorAnomaly(
                    feature="transaction_amount",
                    severity="MEDIUM",
                    deviation=round(txn.amount / avg, 2),
                )
            )
    else:
        baseline.update({"avg_amount": txn.amount, "median_amount": txn.amount, "max_amount": txn.amount})

    devices = {row.get("device_id") for row in history if row.get("device_id")}
    if txn.device_id and devices and txn.device_id not in devices:
        anomalies.append(BehaviorAnomaly(feature="device", severity="MEDIUM"))

    merchants = {row.get("merchant_id") for row in history}
    if history and txn.merchant_id not in merchants:
        anomalies.append(BehaviorAnomaly(feature="merchant", severity="LOW"))

    hours = []
    for row in history:
        raw = row.get("timestamp")
        if raw is None:
            continue
        from datetime import datetime

        ts = raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        hours.append(ts.hour)
    if hours:
        usual = {h for h in set(hours) if hours.count(h) >= 2}
        if usual and txn.timestamp.hour not in usual:
            anomalies.append(BehaviorAnomaly(feature="hour_of_day", severity="LOW"))

    score = 0
    for item in anomalies:
        score += {"HIGH": 35, "MEDIUM": 20, "LOW": 10}[item.severity]
    return BehaviorResult(
        behavioral_score=min(100, score),
        anomalies=tuple(anomalies),
        baseline=baseline,
    )
