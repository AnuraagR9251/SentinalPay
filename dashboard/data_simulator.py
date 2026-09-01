"""Synthetic UPI transaction stream for the Streamlit dashboard.

The UI talks only to a `TransactionSource`. Swap `SimulatedStream` for
`HttpTransactionSource` when the FastAPI feed exists — no dashboard
rewrite required.

# TODO: apply rate limiting here before production use
# TODO: persist via parameterized queries / ORM only — never string-formatted SQL
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from random import Random
from typing import Deque, Iterable, Protocol

from detection import score_transaction
from detection.models import RiskAssessment, Transaction, UserProfile

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


class HttpTransactionSource:
    """Placeholder for a future FastAPI-backed feed.

    The dashboard can be pointed at this class without changing UI logic.

    # TODO: apply rate limiting here before production use
    # TODO: persist via parameterized queries / ORM only — never string-formatted SQL
    """

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def next_batch(self, n: int = 1) -> list[tuple[Transaction, RiskAssessment]]:
        raise NotImplementedError(
            f"Wire this to GET {self.base_url}/transactions once the API exists"
        )

    def snapshot(self) -> list[tuple[Transaction, RiskAssessment]]:
        raise NotImplementedError(
            f"Wire this to GET {self.base_url}/transactions once the API exists"
        )


def iter_scored(pairs: Iterable[tuple[Transaction, RiskAssessment]]) -> Iterable[tuple[Transaction, RiskAssessment]]:
    """Identity helper so callers can map over any TransactionSource snapshot."""
    yield from pairs
