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

    def ingest_event(self, *, body: bytes, signature: str | None, headers: dict[str, str]) -> dict[str, Any]:
        del headers
        if not self.verify_signature(body, signature):
            return {"accepted": False, "error": "invalid_signature"}
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return {"accepted": False, "error": "invalid_json"}
        event_id = str(payload.get("id") or payload.get("event") or "")
        entity = ((payload.get("payload") or {}).get("payment") or {}).get("entity") or {}
        payment_id = str(entity.get("id") or "")
        created = int(payload.get("created_at") or entity.get("created_at") or 0)
        prior = self._events.get(event_id)
        if prior:
            return {"accepted": True, "duplicate": True, "event_id": event_id, "status": prior.get("status")}
        # Out-of-order: keep the newest created_at per payment_id.
        status = map_razorpay_status(entity.get("status"))
        prior_created = self._latest_created.get(payment_id, 0)
        if payment_id and created and created < prior_created:
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
            amount=float(entity.get("amount") or 0) / 100.0,
            currency=str(entity.get("currency") or "INR"),
            status=status,
            order_id=str(entity.get("order_id") or "") or None,
        )
        if payment_id:
            self._payments[payment_id] = ref
            if created >= prior_created:
                self._latest_created[payment_id] = created
        record = {"event_id": event_id, "status": status, "created_at": created, "payment_id": payment_id}
        if event_id:
            self._events[event_id] = record
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

    def fetch_status(self, provider_payment_id: str) -> PaymentRef:
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
