"""Internal contracts. Layers speak these types, not FastAPI models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass(frozen=True)
class NormalizedTransaction:
    transaction_id: str
    user_id: str
    amount: float
    currency: str
    merchant_id: str
    merchant_category: str
    timestamp: datetime
    device_id: Optional[str]
    ip_address: Optional[str]
    latitude: Optional[float]
    longitude: Optional[float]
    recent_failures: int = 0
    payment_type: Optional[str] = None
    origin_balance: Optional[float] = None
    new_origin_balance: Optional[float] = None


@dataclass(frozen=True)
class TriggeredRule:
    rule: str
    severity: str
    score: int
    reason: str


@dataclass(frozen=True)
class SecuritySignals:
    duplicate_transaction: bool
    replay_detected: bool
    invalid_request: bool
    rate_limited: bool
    security_risk_score: int
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuleResult:
    rule_score: int
    triggered_rules: tuple[TriggeredRule, ...]


@dataclass(frozen=True)
class BehaviorAnomaly:
    feature: str
    severity: str
    deviation: Optional[float] = None


@dataclass(frozen=True)
class BehaviorResult:
    behavioral_score: int
    anomalies: tuple[BehaviorAnomaly, ...]
    baseline: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MlResult:
    fraud_probability: float
    model_version: str
    features: dict[str, float] = field(default_factory=dict)
    available: bool = True
    error: str | None = None
    calibrated_for_upi: bool = False
    evaluation: str | None = None


@dataclass(frozen=True)
class RiskFactor:
    factor: str
    impact: str


@dataclass(frozen=True)
class DecisionResult:
    risk_score: int
    decision: str
    confidence: float
    risk_factors: tuple[RiskFactor, ...]
    components: dict[str, float] = field(default_factory=dict)
    fraud_probability: float = 0.0
    policy: dict[str, Any] = field(default_factory=dict)
