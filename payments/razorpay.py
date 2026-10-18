"""Razorpay TEST-MODE adapter.

Uses official HMAC-SHA256 webhook signatures (X-Razorpay-Signature).
Live REST calls only when RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET are set.
This service scores; it cannot pause Razorpay authorization.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from payments.protocol import PaymentRef, map_razorpay_status, redirect_is_not_success

API_ROOT = "https://api.razorpay.com/v1"


class RazorpayConfigError(RuntimeError):
    pass


class RazorpayTestAdapter:
    provider = "razorpay_test"

    def __init__(
        self,
        *,
        key_id: str | None = None,
        key_secret: str | None = None,
        webhook_secret: str | None = None,
    ) -> None:
        self.key_id = (key_id if key_id is not None else os.getenv("RAZORPAY_KEY_ID", "")).strip()
        self.key_secret = (key_secret if key_secret is not None else os.getenv("RAZORPAY_KEY_SECRET", "")).strip()
        self.webhook_secret = (
            webhook_secret if webhook_secret is not None else os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
        ).strip()
        self._events: dict[str, dict[str, Any]] = {}
        self._payments: dict[str, PaymentRef] = {}
        self._latest_created: dict[str, int] = {}
        self._lock = threading.Lock()

    def configured(self) -> bool:
        return bool(self.key_id and self.key_secret)

    def verify_signature(self, body: bytes, signature: str | None) -> bool:
        if not self.webhook_secret or not signature:
            return False
        expected = hmac.new(self.webhook_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature.strip())

    def create_or_reference(
        self,
        *,
        amount: float,
        currency: str,
        receipt: str,
        notes: dict[str, Any] | None = None,
    ) -> PaymentRef:
        if not self.configured():
            raise RazorpayConfigError("RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET required for live TEST calls")
        payload = json.dumps(
            {
                "amount": int(round(amount * 100)),
                "currency": currency,
                "receipt": receipt,
                "notes": notes or {},
            }
        ).encode("utf-8")
        req = Request(
            f"{API_ROOT}/orders",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        req.add_header("Authorization", _basic(self.key_id, self.key_secret))
        try:
            with urlopen(req, timeout=8) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except URLError as exc:
            raise RazorpayConfigError(f"razorpay timeout or network error: {exc}") from exc
        ref = PaymentRef(
            provider=self.provider,
            provider_payment_id=str(body.get("id") or receipt),
            amount=amount,
            currency=currency,
            status=map_razorpay_status(body.get("status")),
            order_id=str(body.get("id") or ""),
        )
        self._payments[ref.provider_payment_id] = ref
        return ref

    def ingest_event(
        self,
        *,
        body: bytes,
        signature: str | None,
        headers: dict[str, str],
        ledger: Any | None = None,
    ) -> dict[str, Any]:
        if not self.verify_signature(body, signature):
            return {"accepted": False, "error": "invalid_signature"}
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return {"accepted": False, "error": "invalid_json"}
        with self._lock:
            return self._ingest_verified(payload, body, headers, ledger)

    def _ingest_verified(
        self,
        payload: dict[str, Any],
        body: bytes,
        headers: dict[str, str],
        ledger: Any | None,
    ) -> dict[str, Any]:
        # Razorpay: x-razorpay-event-id is unique per event (idempotency). Body id is fallback.
        event_id = _webhook_event_id(headers, payload)
        if not event_id:
            return {"accepted": False, "error": "missing_event_id"}
        entity = ((payload.get("payload") or {}).get("payment") or {}).get("entity") or {}
        payment_id = str(entity.get("id") or "").strip()
        try:
            created = int(payload.get("created_at") or entity.get("created_at") or 0)
        except (TypeError, ValueError):
            created = 0
        now = int(time.time())
        max_age = int(os.getenv("SENTINALPAY_WEBHOOK_MAX_AGE_SECONDS", "259200") or 259200)
        if created <= 0 or created > now + 300 or now - created > max_age:
            return {"accepted": False, "error": "stale_or_future_event"}
        status = map_razorpay_status(entity.get("status"))
        payload_hash = hashlib.sha256(body).hexdigest()
        amount = float(entity.get("amount") or 0) / 100.0
        currency = str(entity.get("currency") or "INR")
        order_id = str(entity.get("order_id") or "") or None

        if ledger is not None:
            claimed = ledger.claim_payment_event(
                event_id=event_id,
                payment_id=payment_id,
                status=status,
                provider_created_at=created,
                payload_hash=payload_hash,
                amount=amount,
                currency=currency,
                order_id=order_id,
            )
            if claimed.get("duplicate"):
                return {
                    "accepted": True,
                    "duplicate": True,
                    "event_id": event_id,
                    "status": claimed.get("status"),
                }
            if claimed.get("out_of_order"):
                return {
                    "accepted": True,
                    "out_of_order": True,
                    "event_id": event_id,
                    "status": claimed.get("status") or "unknown",
                    "note": "older event ignored",
                }
        else:
            prior = self._events.get(event_id)
            if prior:
                return {"accepted": True, "duplicate": True, "event_id": event_id, "status": prior.get("status")}
            prior_created = self._latest_created.get(payment_id, 0)
            if payment_id and created < prior_created:
                return {
                    "accepted": True,
                    "out_of_order": True,
                    "event_id": event_id,
                    "status": self._payments[payment_id].status if payment_id in self._payments else "unknown",
                    "note": "older event ignored",
                }

        ref = PaymentRef(
            provider=self.provider,
            provider_payment_id=payment_id or event_id,
            amount=amount,
            currency=currency,
            status=status,
            order_id=order_id,
        )
        if payment_id:
            self._payments[payment_id] = ref
            self._latest_created[payment_id] = max(created, self._latest_created.get(payment_id, 0))
        self._events[event_id] = {
            "event_id": event_id,
            "status": status,
            "created_at": created,
            "payment_id": payment_id,
        }
        return {
            "accepted": True,
            "duplicate": False,
            "event_id": event_id,
            "status": status,
            "payment": {
                "provider": ref.provider,
                "id": ref.provider_payment_id,
                "status": ref.status,
                "amount": ref.amount,
                "currency": ref.currency,
                "order_id": ref.order_id,
            },
        }

    def fetch_status(self, provider_payment_id: str, ledger: Any | None = None) -> PaymentRef:
        if ledger is not None:
            row = ledger.get_provider_payment(provider_payment_id)
            if row:
                return PaymentRef(
                    provider=self.provider,
                    provider_payment_id=provider_payment_id,
                    amount=float(row.get("amount") or 0),
                    currency=str(row.get("currency") or "INR"),
                    status=str(row.get("status") or "unknown"),
                    order_id=row.get("order_id"),
                )
        cached = self._payments.get(provider_payment_id)
        if cached:
            return cached
        if not self.configured():
            raise RazorpayConfigError("keys required to fetch Razorpay status")
        req = Request(f"{API_ROOT}/payments/{provider_payment_id}", method="GET")
        req.add_header("Authorization", _basic(self.key_id, self.key_secret))
        try:
            with urlopen(req, timeout=8) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except URLError as exc:
            raise RazorpayConfigError(f"razorpay fetch failed: {exc}") from exc
        ref = PaymentRef(
            provider=self.provider,
            provider_payment_id=str(body.get("id") or provider_payment_id),
            amount=float(body.get("amount") or 0) / 100.0,
            currency=str(body.get("currency") or "INR"),
            status=map_razorpay_status(body.get("status")),
            order_id=str(body.get("order_id") or "") or None,
        )
        self._payments[ref.provider_payment_id] = ref
        return ref

    def from_redirect(self, query: dict[str, Any] | None = None) -> dict[str, Any]:
        return redirect_is_not_success(query)


def _webhook_event_id(headers: dict[str, str] | None, payload: dict[str, Any]) -> str:
    for key, value in (headers or {}).items():
        if str(key).lower() == "x-razorpay-event-id":
            token = str(value or "").strip()
            if token:
                return token
    return str(payload.get("id") or "").strip()


def _basic(key_id: str, key_secret: str) -> str:
    import base64

    token = base64.b64encode(f"{key_id}:{key_secret}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


_ADAPTER: RazorpayTestAdapter | None = None


def get_razorpay_adapter() -> RazorpayTestAdapter:
    global _ADAPTER
    if _ADAPTER is None:
        _ADAPTER = RazorpayTestAdapter()
    return _ADAPTER
