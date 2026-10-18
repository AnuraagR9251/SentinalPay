"""Synthetic UPI transaction stream for the Streamlit dashboard.

The UI talks only to a `TransactionSource`. Swap `SimulatedStream` for
`HttpTransactionSource` when the FastAPI feed exists — no dashboard
rewrite required.

# TODO: apply rate limiting here before production use
# TODO: persist via parameterized queries / ORM only — never string-formatted SQL
"""

from __future__ import annotations

import json
import os
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from random import Random
from typing import Any, Deque, Iterable, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from detection import score_transaction
from detection.models import (
    FeatureContribution,
    PaymentRiskLabel,
    RiskAssessment,
    RiskTier,
    Transaction,
    UserProfile,
)

BUFFER_MAX: int = 50
STRUCTURING_AMOUNT: float = 49_900.0
CLEAN_FRAUD_SPLIT: float = 0.80


@dataclass(frozen=True)
class _Persona:
    user_id: str
    display_name: str
    home_lat: float
    home_lon: float
    typical_amount: float
    known_payees: tuple[str, ...]
    device_id: str
    home_ip: str


# Synthetic users only — names and VPAs are fictional.
_PERSONAS: tuple[_Persona, ...] = (
    _Persona("usr_priya", "Priya", 18.5204, 73.8567, 380.0, ("kirana.pune@oksbi", "metro.pune@okicici"), "dev-priya-1001", "49.36.10.21"),
    _Persona("usr_arjun", "Arjun", 19.0760, 72.8777, 520.0, ("cafe.bandra@oksbi", "local.train@okaxis"), "dev-arjun-1002", "103.21.44.10"),
    _Persona("usr_neha", "Neha", 28.6139, 77.2090, 640.0, ("sabzi.cp@okicici", "delhi.metro@oksbi"), "dev-neha-1003", "122.162.8.44"),
    _Persona("usr_vikram", "Vikram", 12.9716, 77.5946, 710.0, ("filter.coffee@oksbi", "bmtc.bus@okaxis"), "dev-vikram-1004", "49.207.12.9"),
    _Persona("usr_meera", "Meera", 17.3850, 78.4867, 450.0, ("biryani.hyd@oksbi", "mmts.hyd@okicici"), "dev-meera-1005", "157.48.23.17"),
    _Persona("usr_rohan", "Rohan", 13.0827, 80.2707, 390.0, ("filter.chennai@oksbi", "mrts.chennai@okaxis"), "dev-rohan-1006", "117.192.55.3"),
    _Persona("usr_kabir", "Kabir", 18.5204, 73.8567, 410.0, ("tiffin.pune@oksbi", "auto.pune@okicici"), "dev-kabir-1007", "49.36.88.102"),
)

_REMOTE_CITIES: tuple[tuple[float, float], ...] = (
    (28.6139, 77.2090),  # Delhi
    (19.0760, 72.8777),  # Mumbai
    (12.9716, 77.5946),  # Bengaluru
    (22.5726, 88.3639),  # Kolkata
)

_MULE_VPAS: tuple[str, ...] = (
    "quick.cashout@okaxis",
    "wallet.relay@oksbi",
    "newpayee.unknown@okicici",
)

VPN_DEMO_IP: str = "198.51.100.77"


class TransactionSource(Protocol):
    """Pluggable feed. Dashboard code depends on this protocol only."""

    def next_batch(self, n: int = 1) -> list[tuple[Transaction, RiskAssessment]]:
        """Pull the next n scored transactions and append them to the buffer."""

    def snapshot(self) -> list[tuple[Transaction, RiskAssessment]]:
        """Newest-first view of the in-memory ring buffer."""


class SimulatedStream:
    """In-memory generator of mixed clean / fraud UPI traffic.

    Fraud mix (~20%): account takeover, velocity burst, structuring,
    and occasional impossible travel. Each event is scored through the
    public `score_transaction` function only.
    """

    def __init__(self, *, seed: int = 7102, buffer_max: int = BUFFER_MAX) -> None:
        self._rng = Random(seed)
        self._clock = datetime(2026, 6, 15, 9, 0, tzinfo=timezone.utc)
        self._buffer: Deque[tuple[Transaction, RiskAssessment]] = deque(maxlen=buffer_max)
        self._histories: dict[str, list[Transaction]] = {p.user_id: [] for p in _PERSONAS}
        self._seq = 0
        self._seed_baselines()

    def _persona(self, user_id: str) -> _Persona:
        for persona in _PERSONAS:
            if persona.user_id == user_id:
                return persona
        raise KeyError(user_id)

    def _profile(self, persona: _Persona) -> UserProfile:
        return UserProfile(
            user_id=persona.user_id,
            home_lat=persona.home_lat,
            home_lon=persona.home_lon,
            known_payees=frozenset(persona.known_payees),
        )

    def _next_id(self) -> str:
        self._seq += 1
        return f"TXN{self._seq:06d}"

    def _advance(self, seconds: float) -> datetime:
        self._clock = self._clock + timedelta(seconds=seconds)
        return self._clock

    def _score_and_store(self, txn: Transaction, persona: _Persona) -> tuple[Transaction, RiskAssessment]:
        history = list(self._histories[persona.user_id])
        assessment = score_transaction(txn, history, self._profile(persona))
        self._histories[persona.user_id].append(txn)
        pair = (txn, assessment)
        self._buffer.appendleft(pair)
        return pair

    def _jitter_home(self, persona: _Persona) -> tuple[float, float]:
        return (
            persona.home_lat + self._rng.uniform(-0.01, 0.01),
            persona.home_lon + self._rng.uniform(-0.01, 0.01),
        )

    def _build_txn(
        self,
        persona: _Persona,
        *,
        amount: float,
        payee_vpa: str,
        timestamp: datetime,
        lat: float,
        lon: float,
        ip_address: str,
        device_id: str,
        purpose: str,
        drain: bool = False,
        payee_lat: float | None = None,
        payee_lon: float | None = None,
    ) -> Transaction:
        origin = round(amount if drain else persona.typical_amount * self._rng.uniform(40.0, 90.0), 2)
        if drain:
            origin = round(amount, 2)
        new_origin = 0.0 if drain else max(0.0, round(origin - amount, 2))
        if payee_lat is None or payee_lon is None:
            payee_lat, payee_lon = self._jitter_home(persona)
        return Transaction(
            transaction_id=self._next_id(),
            user_id=persona.user_id,
            amount=round(amount, 2),
            payee_vpa=payee_vpa,
            timestamp=timestamp,
            lat=lat,
            lon=lon,
            payee_lat=payee_lat,
            payee_lon=payee_lon,
            ip_address=ip_address,
            device_id=device_id,
            purpose=purpose,
            origin_balance=origin,
            new_origin_balance=new_origin,
        )

    def _seed_baselines(self) -> None:
        """Give every user a quiet fortnight of clean spend so z-scores exist."""
        for persona in _PERSONAS:
            for day in range(12, 0, -1):
                lat, lon = self._jitter_home(persona)
                txn = self._build_txn(
                    persona,
                    amount=persona.typical_amount + self._rng.uniform(-40, 40),
                    payee_vpa=self._rng.choice(persona.known_payees),
                    timestamp=self._clock - timedelta(days=day, hours=self._rng.randint(0, 5)),
                    lat=lat,
                    lon=lon,
                    ip_address=persona.home_ip,
                    device_id=persona.device_id,
                    purpose="merchant_payment",
                )
                # Seed history without filling the live feed buffer.
                self._histories[persona.user_id].append(txn)

    def _emit_clean(self) -> tuple[Transaction, RiskAssessment]:
        persona = self._rng.choice(_PERSONAS)
        lat, lon = self._jitter_home(persona)
        ts = self._advance(self._rng.uniform(20, 90))
        txn = self._build_txn(
            persona,
            amount=max(40.0, persona.typical_amount + self._rng.gauss(0, 35)),
            payee_vpa=self._rng.choice(persona.known_payees),
            timestamp=ts,
            lat=lat,
            lon=lon,
            ip_address=persona.home_ip,
            device_id=persona.device_id,
            purpose="merchant_payment",
        )
        return self._score_and_store(txn, persona)

    def _emit_account_takeover(self) -> list[tuple[Transaction, RiskAssessment]]:
        persona = self._rng.choice(_PERSONAS)
        remote = self._rng.choice(_REMOTE_CITIES)
        # Avoid picking the user's own city as the "remote" hop when possible.
        if abs(remote[0] - persona.home_lat) < 0.3:
            remote = (28.6139, 77.2090) if persona.home_lat < 20 else (12.9716, 77.5946)
        rows: list[tuple[Transaction, RiskAssessment]] = []
        for _ in range(3):
            ts = self._advance(self._rng.uniform(8, 15))
            txn = self._build_txn(
                persona,
                amount=self._rng.uniform(42_000, 49_500),
                payee_vpa=self._rng.choice(_MULE_VPAS),
                timestamp=ts,
                lat=remote[0] + self._rng.uniform(-0.01, 0.01),
                lon=remote[1] + self._rng.uniform(-0.01, 0.01),
                ip_address=VPN_DEMO_IP,
                device_id="dev-unknown-9999",
                purpose="p2p_transfer",
                drain=True,
                payee_lat=remote[0],
                payee_lon=remote[1],
            )
            rows.append(self._score_and_store(txn, persona))
        return rows

    def _emit_velocity_burst(self) -> list[tuple[Transaction, RiskAssessment]]:
        persona = self._rng.choice(_PERSONAS)
        lat, lon = self._jitter_home(persona)
        rows: list[tuple[Transaction, RiskAssessment]] = []
        for _ in range(6):
            ts = self._advance(self._rng.uniform(4, 9))
            txn = self._build_txn(
                persona,
                amount=self._rng.uniform(800, 2_400),
                payee_vpa=self._rng.choice(_MULE_VPAS + persona.known_payees),
                timestamp=ts,
                lat=lat,
                lon=lon,
                ip_address=persona.home_ip,
                device_id=persona.device_id,
                purpose="p2p_transfer",
            )
            rows.append(self._score_and_store(txn, persona))
        return rows

    def _emit_structuring(self) -> list[tuple[Transaction, RiskAssessment]]:
        persona = self._rng.choice(_PERSONAS)
        lat, lon = self._jitter_home(persona)
        rows: list[tuple[Transaction, RiskAssessment]] = []
        for _ in range(4):
            ts = self._advance(self._rng.uniform(40, 80))
            mule_city = self._rng.choice(_REMOTE_CITIES)
            txn = self._build_txn(
                persona,
                amount=STRUCTURING_AMOUNT - self._rng.uniform(0, 400),
                payee_vpa=self._rng.choice(_MULE_VPAS),
                timestamp=ts,
                lat=lat,
                lon=lon,
                ip_address=persona.home_ip,
                device_id=persona.device_id,
                purpose="p2p_transfer",
                payee_lat=mule_city[0],
                payee_lon=mule_city[1],
            )
            rows.append(self._score_and_store(txn, persona))
        return rows

    def _emit_impossible_travel(self) -> tuple[Transaction, RiskAssessment]:
        persona = self._rng.choice(_PERSONAS)
        remote = self._rng.choice(_REMOTE_CITIES)
        if abs(remote[0] - persona.home_lat) < 0.3:
            remote = (22.5726, 88.3639)
        # Drop an at-home ping, then a far-away ping seconds later.
        local_ts = self._advance(self._rng.uniform(15, 40))
        local = self._build_txn(
            persona,
            amount=persona.typical_amount,
            payee_vpa=persona.known_payees[0],
            timestamp=local_ts,
            lat=persona.home_lat,
            lon=persona.home_lon,
            ip_address=persona.home_ip,
            device_id=persona.device_id,
            purpose="merchant_payment",
        )
        self._score_and_store(local, persona)
        far_ts = self._advance(self._rng.uniform(6, 12) * 60)  # 6–12 minutes later
        far = self._build_txn(
            persona,
            amount=persona.typical_amount * 1.1,
            payee_vpa=persona.known_payees[0],
            timestamp=far_ts,
            lat=remote[0],
            lon=remote[1],
            ip_address=VPN_DEMO_IP,
            device_id=persona.device_id,
            purpose="merchant_payment",
        )
        return self._score_and_store(far, persona)

    def next_batch(self, n: int = 1) -> list[tuple[Transaction, RiskAssessment]]:
        emitted: list[tuple[Transaction, RiskAssessment]] = []
        produced = 0
        while produced < n:
            roll = self._rng.random()
            if roll < CLEAN_FRAUD_SPLIT:
                emitted.append(self._emit_clean())
                produced += 1
            else:
                pattern = self._rng.choice(
                    ("ato", "velocity", "structuring", "impossible")
                )
                if pattern == "ato":
                    rows = self._emit_account_takeover()
                elif pattern == "velocity":
                    rows = self._emit_velocity_burst()
                elif pattern == "structuring":
                    rows = self._emit_structuring()
                else:
                    rows = [self._emit_impossible_travel()]
                emitted.extend(rows)
                produced += len(rows)
        return emitted

    def snapshot(self) -> list[tuple[Transaction, RiskAssessment]]:
        return list(self._buffer)

    def prime(self, n: int = 18) -> None:
        """Pre-fill the live feed so the first dashboard render is not empty.

        An ATO burst and an impossible-travel pair are always included so a
        reviewer opening the desk immediately sees Block / Step-up rows, not
        only clean Allow traffic.
        """
        self._emit_account_takeover()
        self._emit_impossible_travel()
        self.next_batch(n)


def _parse_ts(raw: Any) -> datetime:
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    text = str(raw).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _tier(raw: Any) -> RiskTier | None:
    try:
        return RiskTier(str(raw))
    except ValueError:
        return None


def merge_feed(
    existing: list[tuple[Transaction, RiskAssessment]],
    incoming: list[tuple[Transaction, RiskAssessment]],
    limit: int = BUFFER_MAX,
) -> list[tuple[Transaction, RiskAssessment]]:
    """Last write wins per transaction_id; newest timestamp first."""
    by_id: dict[str, tuple[Transaction, RiskAssessment]] = {
        txn.transaction_id: (txn, assessment) for txn, assessment in existing
    }
    for txn, assessment in incoming:
        by_id[txn.transaction_id] = (txn, assessment)
    merged = sorted(
        by_id.values(),
        key=lambda pair: (pair[0].timestamp, pair[0].transaction_id),
        reverse=True,
    )
    return merged[:limit]


def feed_rows(payload: Any) -> list[Any] | None:
    """Pull the case list out of either the nested envelope or a legacy array."""
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return payload["items"]
    if isinstance(payload, list):
        return payload
    return None


def _flatten_case(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize nested GET /transactions cases onto the desk's flat keys."""
    payment = item.get("payment")
    if not isinstance(payment, dict):
        return item
    location = payment.get("location") if isinstance(payment.get("location"), dict) else {}
    canonical = item.get("canonical") if isinstance(item.get("canonical"), dict) else {}
    policy = item.get("policy") if isinstance(item.get("policy"), dict) else {}
    models = item.get("models") if isinstance(item.get("models"), dict) else {}
    xgb = models.get("xgboost") if isinstance(models.get("xgboost"), dict) else {}
    ae = models.get("autoencoder") if isinstance(models.get("autoencoder"), dict) else {}
    graph = models.get("graph") if isinstance(models.get("graph"), dict) else {}
    return {
        "transaction_id": payment.get("id") or item.get("transaction_id"),
        "user_id": payment.get("user_id"),
        "amount": payment.get("amount"),
        "payee_vpa": payment.get("payee_vpa"),
        "timestamp": payment.get("timestamp"),
        "lat": location.get("lat"),
        "lon": location.get("lon"),
        "purpose": payment.get("purpose"),
        "risk_score": policy.get("legacy_score"),
        "risk_tier": policy.get("legacy_tier") or policy.get("action"),
        "canonical_decision": canonical.get("decision"),
        "canonical_risk_score": canonical.get("risk_score"),
        "P_xgb": xgb.get("value"),
        "P_ae": ae.get("value"),
        "P_graph": graph.get("value"),
        "P_hybrid": policy.get("legacy_score"),
        "ae_available": bool(ae.get("available")),
        "graph_available": bool(graph.get("available")),
        "ml_available": xgb.get("available"),
        "contributions": item.get("triggered_signals") or [],
    }


def rows_from_feed(payload: Any) -> list[tuple[Transaction, RiskAssessment]]:
    """Map GET /transactions JSON into the desk's (txn, assessment) pairs."""
    rows = feed_rows(payload)
    if rows is None:
        return []
    pairs: list[tuple[Transaction, RiskAssessment]] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        item = _flatten_case(raw)
        if not item.get("transaction_id"):
            continue
        txn_id = str(item["transaction_id"])
        if txn_id in seen:
            continue
        try:
            amount = float(item["amount"])
            score = float(item.get("risk_score") if item.get("risk_score") is not None else item.get("P_hybrid") or 0.0)
            if amount <= 0 or not (0.0 <= score <= 1.0):
                continue
            ts = _parse_ts(item["timestamp"])
        except (KeyError, TypeError, ValueError):
            continue
        tier = _tier(item.get("risk_tier"))
        if tier is None:
            continue
        seen.add(txn_id)
        txn = Transaction(
            transaction_id=txn_id,
            user_id=str(item.get("user_id") or "unknown"),
            amount=amount,
            payee_vpa=str(item.get("payee_vpa") or "unknown"),
            timestamp=ts,
            lat=item.get("lat"),
            lon=item.get("lon"),
            payee_lat=item.get("payee_lat"),
            payee_lon=item.get("payee_lon"),
            purpose=item.get("purpose"),
        )
        hits = item.get("contributions") or item.get("top_contributing_features") or []
        contributions: list[FeatureContribution] = []
        if isinstance(hits, list):
            for hit in hits:
                if not isinstance(hit, dict) or not hit.get("name"):
                    continue
                try:
                    normalized = max(0.0, min(1.0, float(hit.get("value", 0.0))))
                except (TypeError, ValueError):
                    continue
                contributions.append(
                    FeatureContribution(
                        name=str(hit["name"]),
                        raw_value=normalized,
                        normalized=normalized,
                        weight=0.0,
                        weighted_score=normalized,
                    )
                )
        p_xgb = item.get("P_xgb")
        p_ae = item.get("P_ae")
        p_graph = item.get("P_graph")
        p_hybrid = item.get("P_hybrid")
        ml_raw = item.get("ml_label")
        try:
            ml_label = PaymentRiskLabel(str(ml_raw)) if ml_raw else None
        except ValueError:
            ml_label = None
        assessment = RiskAssessment(
            transaction_id=txn.transaction_id,
            score=score,
            tier=tier,
            contributions=tuple(contributions),
            ml_label=ml_label,
            ml_probabilities=(),
            p_xgb=None if p_xgb is None else float(p_xgb),
            p_ae=None if p_ae is None else float(p_ae),
            p_graph=None if p_graph is None else float(p_graph),
            p_hybrid=None if p_hybrid is None else float(p_hybrid),
            canonical_decision=item.get("canonical_decision"),
            ae_available=bool(item.get("ae_available")),
            graph_available=bool(item.get("graph_available")),
            ml_available=item.get("ml_available"),
        )
        pairs.append((txn, assessment))
    return pairs


class HttpTransactionSource:
    """Live feed: GET {base_url}/transactions (payments the app already scored).

    Never falls back to SimulatedStream. Empty 200s clear the window.
    Transport failures keep the last successful buffer.
    """

    def __init__(self, base_url: str | None = None) -> None:
        raw = (base_url or os.getenv("SENTINALPAY_SCORE_API") or "http://127.0.0.1:8000").strip()
        self.base_url = raw.rstrip("/")
        self._buffer: list[tuple[Transaction, RiskAssessment]] = []
        self.last_error: str | None = None
        self.last_ok_at: datetime | None = None

    def pull(self) -> list[tuple[Transaction, RiskAssessment]]:
        req = Request(
            f"{self.base_url}/transactions?limit=50",
            headers={"Accept": "application/json"},
            method="GET",
        )
        try:
            with urlopen(req, timeout=3) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError, ValueError) as exc:
            self.last_error = type(exc).__name__
            return list(self._buffer)
        rows = feed_rows(payload)
        if rows is None:
            self.last_error = "InvalidPayload"
            return list(self._buffer)
        incoming = rows_from_feed(payload)
        self.last_error = None
        self.last_ok_at = datetime.now(timezone.utc)
        if rows == []:
            self._buffer = []
        else:
            self._buffer = merge_feed(self._buffer, incoming)
        return list(self._buffer)

    def next_batch(self, n: int = 1) -> list[tuple[Transaction, RiskAssessment]]:
        del n
        return self.pull()

    def snapshot(self) -> list[tuple[Transaction, RiskAssessment]]:
        if not self._buffer and self.last_error is None and self.last_ok_at is None:
            self.pull()
        return list(self._buffer)


def iter_scored(pairs: Iterable[tuple[Transaction, RiskAssessment]]) -> Iterable[tuple[Transaction, RiskAssessment]]:
    """Identity helper so callers can map over any TransactionSource snapshot."""
    yield from pairs
