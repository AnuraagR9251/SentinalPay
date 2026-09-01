"""Unit tests for the public scoring API.

Cases map to the milestone contract: a clean payment stays ALLOW, an
account-takeover pattern blocks, impossible travel fires, and edge cases
(new user, missing geo, malformed input) fail safely.
"""

from __future__ import annotations

import copy
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from detection.models import RiskTier, Transaction, UserProfile
from detection.privacy import mask_identifier, mask_vpa
from detection.scoring_engine import score_transaction
from detection.validation import ScoringValidationError

# Pune (home), Mumbai, Delhi — real city centres for realistic haversine.
PUNE = (18.5204, 73.8567)
MUMBAI = (19.0760, 72.8777)
DELHI = (28.6139, 77.2090)

HOME_PAYEE = "kirana.store@oksbi"
RENT_PAYEE = "landlord.pune@okicici"
KNOWN_PAYEES = frozenset({HOME_PAYEE, RENT_PAYEE})

VPN_IP = "198.51.100.40"  # RFC 5737 TEST-NET-2 — flagged by built-in CIDR
CLEAN_IP = "49.36.12.8"  # typical Indian broadband, not in the VPN list


def _ts(minutes_ago: float, *, now: datetime | None = None) -> datetime:
    base = now or datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    return base - timedelta(minutes=minutes_ago)


def _txn(
    *,
    transaction_id: str = "txn_current",
    user_id: str = "user_pune_1",
    amount: float = 450.0,
    payee_vpa: str = HOME_PAYEE,
    timestamp: datetime | None = None,
    lat: float | None = PUNE[0],
    lon: float | None = PUNE[1],
    ip_address: str | None = CLEAN_IP,
    device_id: str | None = "dev-pune-aa11",
) -> dict[str, Any]:
    return {
        "transaction_id": transaction_id,
        "user_id": user_id,
        "amount": amount,
        "payee_vpa": payee_vpa,
        "timestamp": timestamp or _ts(0),
        "lat": lat,
        "lon": lon,
        "ip_address": ip_address,
        "device_id": device_id,
    }


def _history(n: int = 10, *, amount: float = 420.0) -> list[dict[str, Any]]:
    """Stable Pune spend over the last fortnight — a normal retail baseline."""
    rows: list[dict[str, Any]] = []
    payees = [HOME_PAYEE, RENT_PAYEE]
    for i in range(n):
        rows.append(
            _txn(
                transaction_id=f"txn_hist_{i:02d}",
                amount=amount + (i % 3) * 15.0,
                payee_vpa=payees[i % 2],
                timestamp=_ts(90 + i * 24 * 60),  # roughly daily, well outside velocity windows
                lat=PUNE[0] + 0.002 * ((-1) ** i),
                lon=PUNE[1] + 0.002 * ((-1) ** i),
            )
        )
    return rows


def _profile() -> dict[str, Any]:
    return {
        "user_id": "user_pune_1",
        "home_lat": PUNE[0],
        "home_lon": PUNE[1],
        "known_payees": list(KNOWN_PAYEES),
    }


def _contribution(assessment, name: str):
    for item in assessment.contributions:
        if item.name == name:
            return item
    raise AssertionError(f"feature {name!r} missing from contributions")


# ---------------------------------------------------------------------------
# Happy / fraud paths
# ---------------------------------------------------------------------------


def test_four_risk_actions() -> None:
    from detection.scoring_engine import _tier_for

    assert _tier_for(0.20) is RiskTier.ALLOW
    assert _tier_for(0.50) is RiskTier.STEP_UP
    assert _tier_for(0.62) is RiskTier.HOLD
    assert _tier_for(0.80) is RiskTier.BLOCK


def test_normal_transaction_is_allow() -> None:
    assessment = score_transaction(_txn(), _history(), _profile())
    assert assessment.tier is RiskTier.ALLOW
    assert 0.0 <= assessment.score <= 0.40
    assert _contribution(assessment, "new_payee").normalized == 0.0
    assert _contribution(assessment, "vpn_proxy").normalized == 0.0
    assert _contribution(assessment, "impossible_travel").normalized < 0.2


def test_account_takeover_is_block() -> None:
    """ATO: spend spike + first-time mule VPA + VPN egress + city hop + burst.

    Recent history stays on known payees so `new_payee` still fires on the
    first cash-out, while sub-minute repeats saturate velocity.
    """
    now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    history = _history()
    for i in range(5):
        history.append(
            _txn(
                transaction_id=f"txn_burst_{i}",
                amount=430.0,
                payee_vpa=HOME_PAYEE,
                timestamp=now - timedelta(seconds=12 + i * 8),
                lat=PUNE[0],
                lon=PUNE[1],
                ip_address=VPN_IP,
            )
        )
    current = _txn(
        transaction_id="txn_ato",
        amount=49500.0,
        payee_vpa="mule.cashout@okaxis",
        timestamp=now,
        lat=DELHI[0],
        lon=DELHI[1],
        ip_address=VPN_IP,
        device_id="unknown-device-9999",
    )
    assessment = score_transaction(current, history, _profile())
    assert assessment.tier is RiskTier.BLOCK
    assert assessment.score > 0.70
    assert _contribution(assessment, "amount_zscore").normalized == 1.0
    assert _contribution(assessment, "new_payee").normalized == 1.0
    assert _contribution(assessment, "vpn_proxy").normalized == 1.0
    assert _contribution(assessment, "dist_from_home").normalized == 1.0


def test_impossible_travel_feature_saturates() -> None:
    now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    history = _history()
    history.append(
        _txn(
            transaction_id="txn_mumbai",
            amount=400.0,
            payee_vpa=HOME_PAYEE,
            timestamp=now - timedelta(minutes=10),
            lat=MUMBAI[0],
            lon=MUMBAI[1],
        )
    )
    current = _txn(
        transaction_id="txn_delhi",
        amount=400.0,
        payee_vpa=HOME_PAYEE,
        timestamp=now,
        lat=DELHI[0],
        lon=DELHI[1],
    )
    assessment = score_transaction(current, history, _profile())
    travel = _contribution(assessment, "impossible_travel")
    assert travel.raw_value is not None
    assert travel.raw_value > 800.0
    assert travel.normalized == pytest.approx(1.0)
    assert travel.weighted_score == pytest.approx(0.15)


def test_new_user_does_not_auto_block() -> None:
    profile = {
        "user_id": "user_brand_new",
        "home_lat": PUNE[0],
        "home_lon": PUNE[1],
        "known_payees": [],
    }
    current = _txn(user_id="user_brand_new", amount=250.0)
    assessment = score_transaction(current, [], profile)
    assert _contribution(assessment, "amount_zscore").raw_value is None
    assert _contribution(assessment, "amount_zscore").normalized == 0.0
    assert _contribution(assessment, "new_payee").normalized == 1.0
    assert assessment.tier is not RiskTier.BLOCK
    assert assessment.score < 0.70


def test_missing_location_applies_penalty_and_zeros_geo() -> None:
    current = _txn(lat=None, lon=None)
    assessment = score_transaction(current, _history(), _profile())
    assert _contribution(assessment, "dist_from_home").raw_value is None
    assert _contribution(assessment, "dist_from_home").normalized == 0.0
    assert _contribution(assessment, "dist_from_last").raw_value is None
    assert _contribution(assessment, "impossible_travel").raw_value is None
    missing = _contribution(assessment, "missing_location")
    assert missing.normalized == 1.0
    assert missing.weighted_score == pytest.approx(0.05)
    assert 0.0 <= assessment.score <= 1.0


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_negative_amount_is_rejected() -> None:
    with pytest.raises(ScoringValidationError, match="amount"):
        score_transaction(_txn(amount=-10), _history(), _profile())


def test_non_numeric_amount_is_rejected() -> None:
    current = _txn()
    current["amount"] = "not-a-number"
    with pytest.raises(ScoringValidationError, match="amount"):
        score_transaction(current, _history(), _profile())


def test_missing_transaction_id_is_rejected() -> None:
    current = _txn()
    del current["transaction_id"]
    with pytest.raises(ScoringValidationError, match="transaction_id"):
        score_transaction(current, _history(), _profile())


def test_out_of_range_latitude_is_rejected() -> None:
    with pytest.raises(ScoringValidationError, match="lat"):
        score_transaction(_txn(lat=200.0), _history(), _profile())


def test_partial_payee_coordinates_are_rejected() -> None:
    current = _txn()
    current["payee_lat"] = 19.07
    current["payee_lon"] = None
    with pytest.raises(ScoringValidationError, match="payee_lat"):
        score_transaction(current, _history(), _profile())


def test_partial_payee_coordinates_are_rejected() -> None:
    current = _txn()
    current["payee_lat"] = 19.07
    current["payee_lon"] = None
    with pytest.raises(ScoringValidationError, match="payee_lat"):
        score_transaction(current, _history(), _profile())


def test_partial_coordinates_are_rejected() -> None:
    with pytest.raises(ScoringValidationError, match="lat and lon"):
        score_transaction(_txn(lat=18.5, lon=None), _history(), _profile())


def test_malformed_history_item_is_rejected() -> None:
    history = _history()
    history[0]["amount"] = -1
    with pytest.raises(ScoringValidationError, match="amount"):
        score_transaction(_txn(), history, _profile())


# ---------------------------------------------------------------------------
# Purity + dataclass path
# ---------------------------------------------------------------------------


def test_scoring_does_not_mutate_history() -> None:
    history = _history()
    snapshot = copy.deepcopy(history)
    score_transaction(_txn(), history, _profile())
    assert history == snapshot


def test_accepts_dataclasses() -> None:
    now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    txn = Transaction(
        transaction_id="txn_dc",
        user_id="user_pune_1",
        amount=400.0,
        payee_vpa=HOME_PAYEE,
        timestamp=now,
        lat=PUNE[0],
        lon=PUNE[1],
        ip_address=CLEAN_IP,
    )
    prior = [
        Transaction(
            transaction_id="txn_dc_h",
            user_id="user_pune_1",
            amount=390.0,
            payee_vpa=HOME_PAYEE,
            timestamp=now - timedelta(days=2),
            lat=PUNE[0],
            lon=PUNE[1],
        )
    ] * 3
    profile = UserProfile(
        user_id="user_pune_1",
        home_lat=PUNE[0],
        home_lon=PUNE[1],
        known_payees=KNOWN_PAYEES,
    )
    assessment = score_transaction(txn, prior, profile)
    assert assessment.transaction_id == "txn_dc"
    assert assessment.tier is RiskTier.ALLOW


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------


def test_logger_records_only_id_and_score(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="sentinalpay.scoring")
    current = _txn(transaction_id="txn_privacy", amount=777.0, payee_vpa="secret.person@oksbi")
    assessment = score_transaction(current, _history(), _profile())
    assert assessment.transaction_id == "txn_privacy"
    combined = " ".join(record.getMessage() for record in caplog.records)
    assert "txn_privacy" in combined
    assert f"{assessment.score:.4f}" in combined
    assert "secret.person@oksbi" not in combined
    assert "777" not in combined
    assert "18.5204" not in combined


def test_mask_vpa_and_device() -> None:
    assert mask_vpa("anuraag.r@oksbi").endswith("@oksbi")
    assert "anuraag" not in mask_vpa("anuraag.r@oksbi")
    assert mask_identifier("device-abc-9999").endswith("9999")
    assert mask_identifier("device-abc-9999").startswith("*")
