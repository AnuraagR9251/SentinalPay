"""Location and network features for impossible-travel and proxy detection.

Geo signals catch the "same phone, two cities, ten minutes" pattern that
pure amount models miss. All functions are pure and tolerate missing coords.
"""

from __future__ import annotations

from ipaddress import AddressValueError, IPv4Address, IPv6Address, ip_address
from math import asin, cos, inf, radians, sin, sqrt
from typing import Optional, Sequence, Union

from detection.constants import EARTH_RADIUS_KM, VPN_PROXY_NETWORKS
from detection.models import Transaction, UserProfile

_IP = Union[IPv4Address, IPv6Address]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres between two WGS-84 points.

    Why: Euclidean lat/lon degrees are meaningless across India (1° of
    longitude is a different number of km in Kashmir vs Kanyakumari).
    Haversine gives a physical distance we can compare to travel time.
    """
    rlat1, rlon1, rlat2, rlon2 = (radians(lat1), radians(lon1), radians(lat2), radians(lon2))
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    chord = sin(dlat / 2.0) ** 2 + cos(rlat1) * cos(rlat2) * sin(dlon / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_KM * asin(sqrt(min(1.0, chord)))


def has_coordinates(transaction: Transaction) -> bool:
    """True when both lat and lon are present."""
    return transaction.lat is not None and transaction.lon is not None


def distance_from_home(transaction: Transaction, profile: UserProfile) -> Optional[float]:
    """Kilometres between the txn fix and the user's registered home.

    Why: a payment far from the home corridor (and from the last txn) is
    a classic ATO / stolen-device cue, especially overnight. Returns None
    when either side lacks coordinates so the engine can apply a small
    missing-location penalty instead of inventing a distance.
    """
    if not has_coordinates(transaction):
        return None
    if profile.home_lat is None or profile.home_lon is None:
        return None
    return haversine_km(profile.home_lat, profile.home_lon, transaction.lat, transaction.lon)  # type: ignore[arg-type]


def _latest_located_prior(
    transaction: Transaction,
    history: Sequence[Transaction],
) -> Optional[Transaction]:
    located = [
        txn
        for txn in history
        if txn.timestamp <= transaction.timestamp and has_coordinates(txn)
    ]
    if not located:
        return None
    return max(located, key=lambda txn: txn.timestamp)


def distance_from_last(transaction: Transaction, history: Sequence[Transaction]) -> Optional[float]:
    """Kilometres between this txn and the most recent prior txn with a fix.

    Why: a sudden hop (Pune → Delhi) is more suspicious than a slow drift
    along a commute. Used together with elapsed time to get implied speed.
    """
    if not has_coordinates(transaction):
        return None
    prior = _latest_located_prior(transaction, history)
    if prior is None:
        return None
    return haversine_km(prior.lat, prior.lon, transaction.lat, transaction.lon)  # type: ignore[arg-type]


def implied_travel_speed_kmh(
    transaction: Transaction,
    history: Sequence[Transaction],
) -> Optional[float]:
    """Distance-from-last divided by elapsed hours.

    Why: a human (and their phone) cannot be in Mumbai and Delhi ten
    minutes apart. Speeds above commercial-transit limits are "impossible
    travel" — one of the highest-precision location fraud features.
    Returns ``inf`` when two located txns share a timestamp (zero elapsed)
    because that is physically impossible at any non-zero distance.
    Returns None when a distance cannot be computed.
    """
    distance = distance_from_last(transaction, history)
    if distance is None:
        return None
    prior = _latest_located_prior(transaction, history)
    assert prior is not None  # distance_from_last already required this
    elapsed_seconds = (transaction.timestamp - prior.timestamp).total_seconds()
    if elapsed_seconds <= 0:
        return inf if distance > 0 else 0.0
    return distance / (elapsed_seconds / 3600.0)


def is_vpn_or_proxy(ip_value: Optional[str]) -> bool:
    """True when the source IP falls in a known VPN/proxy CIDR.

    Why: fraudsters hide the real egress behind a VPN or datacenter proxy
    so the IP geolocation disagrees with GPS (or so velocity rules that
    key on ISP are blinded). A match is a supporting signal, not a
    standalone block reason. Unparseable IPs are treated as not-VPN so a
    junk address cannot crash scoring.
    """
    if not ip_value:
        return False
    try:
        parsed: _IP = ip_address(ip_value)
    except (AddressValueError, ValueError):
        return False
    return any(parsed in network for network in VPN_PROXY_NETWORKS)
