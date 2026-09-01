"""Typed contracts for the scoring engine.

These dataclasses are the only shapes the public API accepts or returns.
They stay free of FastAPI/Pydantic so the engine remains a pure library.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class RiskTier(str, Enum):
    """Four risk-tiered actions from the SentinalPay architecture."""

    ALLOW = "ALLOW"  # shown as Legit — log only
    STEP_UP = "STEP_UP"  # OTP / re-confirmation
    HOLD = "HOLD"  # delayed settlement
    BLOCK = "BLOCK"  # account lock


class PaymentRiskLabel(str, Enum):
    """ML class for payment purpose / intent risk."""

    LEGIT = "LEGIT"
    SUSPICIOUS = "SUSPICIOUS"
    LIKELY_FRAUD = "LIKELY_FRAUD"


@dataclass(frozen=True)
class Transaction:
    """A single UPI payment event.

    Optional geo/IP/device fields are omitted on older devices or when the
    payer has location services off. The engine treats absence as a weak
    signal, not a hard fail.
    """

    transaction_id: str
    user_id: str
    amount: float
    payee_vpa: str
    timestamp: datetime
    lat: Optional[float] = None
    lon: Optional[float] = None
    payee_lat: Optional[float] = None
    payee_lon: Optional[float] = None
    ip_address: Optional[str] = None
    device_id: Optional[str] = None
    purpose: Optional[str] = None
    origin_balance: Optional[float] = None
    new_origin_balance: Optional[float] = None
    dest_balance: Optional[float] = None
    new_dest_balance: Optional[float] = None


@dataclass(frozen=True)
class UserProfile:
    """Rolling profile used to contextualise a transaction.

    `known_payees` is the set of VPAs the user has previously paid (plus any
    allow-listed contacts). Home coordinates are the user's registered
    address / most-common night-time location — not the current GPS fix.
    """

    user_id: str
    home_lat: Optional[float] = None
    home_lon: Optional[float] = None
    known_payees: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class FeatureContribution:
    """One feature's raw value, 0–1 normalisation, weight, and share of score."""

    name: str
    raw_value: Optional[float]
    normalized: float
    weight: float
    weighted_score: float


@dataclass(frozen=True)
class RiskAssessment:
    """Structured output of `score_transaction`.

    `score` is in [0, 1]. `contributions` always lists every feature so a
    dashboard can explain both what fired and what did not.
    """

    transaction_id: str
    score: float
    tier: RiskTier
    contributions: tuple[FeatureContribution, ...]
    ml_label: Optional[PaymentRiskLabel] = None
    ml_probabilities: tuple[tuple[str, float], ...] = ()
