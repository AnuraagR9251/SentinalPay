"""Stateless behavioural + location risk scoring for UPI transactions.

`score_transaction` is a pure function of (transaction, history, profile):
no globals, no I/O besides an optional info log of id+score, and no
mutation of the caller's history. That contract is what lets a later
FastAPI layer call it concurrently without race conditions.

# TODO: apply rate limiting here before production use
# TODO: persist via parameterized queries / ORM only — never string-formatted SQL
"""

from __future__ import annotations

import logging
from math import inf
from typing import Any, Mapping, Optional, Sequence

from dotenv import load_dotenv

from detection.constants import (
    ALLOW_MAX,
    FEATURE_WEIGHTS,
    HOLD_MAX,
    HOME_DISTANCE_SATURATION_KM,
    IMPOSSIBLE_TRAVEL_SPEED_KMH,
    LAST_TXN_DISTANCE_SATURATION_KM,
    MISSING_LOCATION_PENALTY,
    RAPID_REPLAY_SECONDS,
    STEP_UP_MAX,
    VELOCITY_5M_LIMIT,
    VELOCITY_5M_SECONDS,
    VELOCITY_60M_LIMIT,
    VELOCITY_60M_SECONDS,
    ZSCORE_SATURATION,
)
from detection.features import behavioural, location
from detection.models import (
    FeatureContribution,
    RiskAssessment,
    RiskTier,
    Transaction,
    UserProfile,
)
from detection.ml_classifier import classify_payment
from detection.privacy import log_score
from detection.validation import (
    ScoringValidationError,
    parse_history,
    parse_transaction,
    parse_user_profile,
)

load_dotenv()

logger = logging.getLogger("sentinalpay.scoring")

_WEIGHT_SUM = sum(FEATURE_WEIGHTS.values())
if abs(_WEIGHT_SUM - 1.0) > 1e-9:
    raise RuntimeError(f"FEATURE_WEIGHTS must sum to 1.0, got {_WEIGHT_SUM}")


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _normalise_zscore(raw: Optional[float]) -> float:
    if raw is None:
        return 0.0
    return _clip01(abs(raw) / ZSCORE_SATURATION)


def _normalise_ratio(raw: float, limit: float) -> float:
    if limit <= 0:
        return 0.0
    return _clip01(raw / limit)


def _normalise_time_since(raw: Optional[float]) -> float:
    if raw is None:
        return 0.0
    if raw <= 0:
        return 1.0
    if raw <= RAPID_REPLAY_SECONDS:
        return 1.0
    return _clip01(RAPID_REPLAY_SECONDS / raw)


def _normalise_speed(raw: Optional[float]) -> float:
    if raw is None:
        return 0.0
    if raw is inf or raw >= IMPOSSIBLE_TRAVEL_SPEED_KMH:
        return 1.0
    return _clip01(raw / IMPOSSIBLE_TRAVEL_SPEED_KMH)


def _tier_for(score: float) -> RiskTier:
    if score <= ALLOW_MAX:
        return RiskTier.ALLOW
    if score <= STEP_UP_MAX:
        return RiskTier.STEP_UP
    if score <= HOLD_MAX:
        return RiskTier.HOLD
    return RiskTier.BLOCK


def _contribute(name: str, raw: Optional[float], normalized: float) -> FeatureContribution:
    weight = FEATURE_WEIGHTS.get(name, 0.0)
    return FeatureContribution(
        name=name,
        raw_value=raw,
        normalized=_clip01(normalized),
        weight=weight,
        weighted_score=_clip01(normalized) * weight,
    )


def score_transaction(
    transaction: Transaction | Mapping[str, Any],
    history: Sequence[Transaction | Mapping[str, Any]],
    user_profile: UserProfile | Mapping[str, Any],
) -> RiskAssessment:
    """Compute a 0–1 risk score and per-feature breakdown.

    Parameters
    ----------
    transaction:
        The candidate payment (dataclass or dict). Validated before use.
    history:
        Prior transactions for the same user, oldest or newest first —
        order does not matter. Must not be mutated.
    user_profile:
        Home location and known-payee set used as behavioural baseline.

    Returns
    -------
    RiskAssessment
        Score in [0, 1], a recommended tier, and every feature's
        contribution so an analyst (or the Streamlit dashboard) can see
        *why* the transaction was allowed, held, or blocked.

    Raises
    ------
    ScoringValidationError
        On missing required fields, non-positive amounts, or illegal
        coordinates. Failures are explicit — nothing is silently coerced.

    Notes
    -----
    This function is stateless. A future HTTP adapter should apply rate
    limiting *before* calling it, and any persistence must use
    parameterized queries / an ORM.
    """
    txn = parse_transaction(transaction)
    prior = parse_history(history)
    profile = parse_user_profile(user_profile)

    zscore = behavioural.amount_zscore(txn, prior)
    new_payee = behavioural.is_new_payee(txn, prior, profile)
    vel_5m = behavioural.velocity(txn, prior, VELOCITY_5M_SECONDS)
    vel_60m = behavioural.velocity(txn, prior, VELOCITY_60M_SECONDS)
    gap = behavioural.seconds_since_last(txn, prior)

    dist_home = location.distance_from_home(txn, profile)
    dist_last = location.distance_from_last(txn, prior)
    speed = location.implied_travel_speed_kmh(txn, prior)
    vpn = location.is_vpn_or_proxy(txn.ip_address)
    missing_geo = not location.has_coordinates(txn)

    contributions = (
        _contribute("amount_zscore", zscore, _normalise_zscore(zscore)),
        _contribute("new_payee", 1.0 if new_payee else 0.0, 1.0 if new_payee else 0.0),
        _contribute("velocity_5m", float(vel_5m), _normalise_ratio(float(vel_5m), float(VELOCITY_5M_LIMIT))),
        _contribute("velocity_60m", float(vel_60m), _normalise_ratio(float(vel_60m), float(VELOCITY_60M_LIMIT))),
        _contribute("time_since_last", gap, _normalise_time_since(gap)),
        _contribute(
            "dist_from_home",
            dist_home,
            _normalise_ratio(dist_home, HOME_DISTANCE_SATURATION_KM) if dist_home is not None else 0.0,
        ),
        _contribute(
            "dist_from_last",
            dist_last,
            _normalise_ratio(dist_last, LAST_TXN_DISTANCE_SATURATION_KM) if dist_last is not None else 0.0,
        ),
        _contribute("impossible_travel", speed, _normalise_speed(speed)),
        _contribute("vpn_proxy", 1.0 if vpn else 0.0, 1.0 if vpn else 0.0),
        FeatureContribution(
            name="missing_location",
            raw_value=1.0 if missing_geo else 0.0,
            normalized=1.0 if missing_geo else 0.0,
            weight=MISSING_LOCATION_PENALTY,
            weighted_score=MISSING_LOCATION_PENALTY if missing_geo else 0.0,
        ),
    )

    score = _clip01(sum(item.weighted_score for item in contributions))
    ml = classify_payment(txn)
    assessment = RiskAssessment(
        transaction_id=txn.transaction_id,
        score=score,
        tier=_tier_for(score),
        contributions=contributions,
        ml_label=None if ml is None else ml.label,
        ml_probabilities=() if ml is None else ml.probabilities,
    )
    log_score(logger, assessment.transaction_id, assessment.score)
    if ml is not None:
        logger.info(
            "ml transaction_id=%s label=%s",
            assessment.transaction_id,
            ml.label.value,
        )
    return assessment


__all__ = [
    "ScoringValidationError",
    "score_transaction",
]
