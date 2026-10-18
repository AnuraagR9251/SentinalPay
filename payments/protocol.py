"""Provider-neutral payment states. Browser redirects are never success."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

# Internal states. Provider capture/authorize is authoritative.
STATES = frozenset({"created", "pending", "authorized", "captured", "failed", "unknown"})


@dataclass(frozen=True)
class PaymentRef:
    provider: str
    provider_payment_id: str
    amount: float
    currency: str
    status: str
    order_id: str | None = None


class PaymentAdapter(Protocol):
    provider: str

    def create_or_reference(self, *, amount: float, currency: str, receipt: str, notes: dict[str, Any] | None = None) -> PaymentRef:
        ...

    def ingest_event(self, *, body: bytes, signature: str | None, headers: dict[str, str]) -> dict[str, Any]:
        ...

    def fetch_status(self, provider_payment_id: str) -> PaymentRef:
        ...


def map_razorpay_status(raw: str | None) -> str:
    value = (raw or "").strip().lower()
    return {
        "created": "created",
        "authorized": "authorized",
        "captured": "captured",
        "failed": "failed",
        "refunded": "failed",
    }.get(value, "unknown")


def redirect_is_not_success(_query: dict[str, Any] | None = None) -> dict[str, Any]:
    """Never mark paid from a browser return URL."""
    return {
        "status": "pending",
        "authoritative": False,
        "note": "browser redirect is not confirmation; fetch provider status or wait for a signed webhook",
    }
