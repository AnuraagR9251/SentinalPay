"""Tunable fraud-scoring thresholds and feature weights.

All cutoffs live here so they can be adjusted without hunting magic numbers
through the feature modules. Weights are designed to sum to 1.00.
"""

from __future__ import annotations

import os
from ipaddress import ip_network

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Behavioural thresholds
# ---------------------------------------------------------------------------

# |z| at this value saturates the amount-deviation feature to 1.0.
# A 3-sigma jump is a classic ATO / mule-spend spike on a retail UPI account.
ZSCORE_SATURATION: float = 3.0

# Fewer observations than this makes a z-score statistically meaningless.
# Unknown is not treated as guilty — the feature contributes 0.
MIN_HISTORY_FOR_ZSCORE: int = 3

# Transaction counts that saturate the short- and medium-window velocity
# features. Bursts at or above these levels look like automated drain or
# structuring rather than a person paying a bill.
VELOCITY_5M_LIMIT: int = 5
VELOCITY_60M_LIMIT: int = 12

# Seconds-since-last at or below this value saturates the rapid-replay
# feature. Sub-30s repeats are typical of scripted account drain.
RAPID_REPLAY_SECONDS: float = 30.0

# ---------------------------------------------------------------------------
# Location thresholds
# ---------------------------------------------------------------------------

EARTH_RADIUS_KM: float = 6371.0

# Distance-from-home (km) that saturates the geo-anomaly feature.
# 500 km is well outside a typical daily commuting radius in India.
HOME_DISTANCE_SATURATION_KM: float = 500.0

# Distance-from-last-txn (km) that saturates the hop feature.
LAST_TXN_DISTANCE_SATURATION_KM: float = 200.0

# Implied travel speed (km/h) treated as physically impossible for a
# legitimate card-present / phone-present UPI user. 800 km/h is faster
# than typical commercial transit between Indian metros once airport
# overhead is included.
IMPOSSIBLE_TRAVEL_SPEED_KMH: float = 800.0

# Small standalone penalty when lat/lon are absent. Missing location is a
# weak signal (privacy settings, older devices) — not proof of fraud.
MISSING_LOCATION_PENALTY: float = 0.05

# ---------------------------------------------------------------------------
# Risk-tier cutovers (inclusive upper bounds) — four actions
# Legit (ALLOW) → Step-up Auth → Hold → Block
# ---------------------------------------------------------------------------

ALLOW_MAX: float = 0.40
STEP_UP_MAX: float = 0.55
HOLD_MAX: float = 0.70

# ---------------------------------------------------------------------------
# Feature weights — must sum to 1.00
# ---------------------------------------------------------------------------

WEIGHT_AMOUNT_ZSCORE: float = 0.20
WEIGHT_NEW_PAYEE: float = 0.15
WEIGHT_VELOCITY_5M: float = 0.15
WEIGHT_VELOCITY_60M: float = 0.10
WEIGHT_TIME_SINCE_LAST: float = 0.05
WEIGHT_DIST_HOME: float = 0.10
WEIGHT_DIST_LAST: float = 0.05
WEIGHT_IMPOSSIBLE_TRAVEL: float = 0.15
WEIGHT_VPN_PROXY: float = 0.05

FEATURE_WEIGHTS: dict[str, float] = {
    "amount_zscore": WEIGHT_AMOUNT_ZSCORE,
    "new_payee": WEIGHT_NEW_PAYEE,
    "velocity_5m": WEIGHT_VELOCITY_5M,
    "velocity_60m": WEIGHT_VELOCITY_60M,
    "time_since_last": WEIGHT_TIME_SINCE_LAST,
    "dist_from_home": WEIGHT_DIST_HOME,
    "dist_from_last": WEIGHT_DIST_LAST,
    "impossible_travel": WEIGHT_IMPOSSIBLE_TRAVEL,
    "vpn_proxy": WEIGHT_VPN_PROXY,
}

# ---------------------------------------------------------------------------
# Time windows
# ---------------------------------------------------------------------------

VELOCITY_5M_SECONDS: float = 5.0 * 60.0
VELOCITY_60M_SECONDS: float = 60.0 * 60.0

# ---------------------------------------------------------------------------
# VPN / proxy CIDR detection
# ---------------------------------------------------------------------------
# Static demo ranges only. 198.51.100.0/24 is RFC 5737 TEST-NET-2 — reserved
# documentation space that the simulator uses as a stand-in for a known VPN
# egress. Extra CIDRs may be supplied via SENTINALPAY_VPN_CIDRS (comma-
# separated) so operators can extend the list without committing secrets.

_BUILTIN_VPN_CIDRS: tuple[str, ...] = (
    "198.51.100.0/24",  # RFC 5737 TEST-NET-2 — simulator VPN flag
)


def _load_vpn_networks() -> tuple:
    """Build the VPN/proxy network list from builtins + optional env CIDRs."""
    extra_raw = os.getenv("SENTINALPAY_VPN_CIDRS", "")
    cidrs = list(_BUILTIN_VPN_CIDRS)
    if extra_raw.strip():
        cidrs.extend(part.strip() for part in extra_raw.split(",") if part.strip())
    return tuple(ip_network(cidr, strict=False) for cidr in cidrs)


VPN_PROXY_NETWORKS = _load_vpn_networks()
