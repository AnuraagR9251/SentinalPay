"""HTTP adapter. Scoring lives in risk.pipeline — not here.

POST /score                         — React REST contract (kept)
POST /graphql                       — same engine, GraphQL query/mutation
POST /api/v1/transactions/evaluate  — canonical REST contract
GET  /transactions                  — desk feed
GET  /health
GET  /ready
POST /webhooks/razorpay              — signed TEST webhooks only

# HTTP request limits: risk.auth.protect_sensitive (429). Payment velocity stays in risk.security.
# Persistence uses parameterized SQL in risk.store.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from math import isfinite
from typing import Any

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from api.compat import legacy_fields_from_canonical, pipeline_payload_from_score
from api.httpbody import read_body_capped, webhook_max_bytes
from api.graphql import graphql_router
from api.v1 import router as v1_router
from detection.privacy import mask_identifier
from payments.razorpay import RazorpayApiError, RazorpayConfigError, get_razorpay_adapter
from risk.auth import (
    apply_admin_cookie,
    assert_login_not_locked,
    authenticate_request,
    bearer_token,
    clear_admin_cookie,
    login_throttle_key,
    logout_request,
    note_login_failure,
    open_access_warning,
    protect_sensitive,
    require_admin_csrf,
    require_admin_session,
    require_login,
    require_order_auth,
    require_session,
    verify_pin_request,
)
from risk.ml_layer import model_status
from risk.pipeline import PipelineError, evaluate_transaction, http_status_for_pipeline_error
from risk.secondary import resolve_hold, same_binding
from risk.store import get_store

load_dotenv()

logger = logging.getLogger("sentinalpay.api")
logging.basicConfig(level=os.getenv("SENTINALPAY_LOG_LEVEL", "INFO"))


class PayerLocation(BaseModel):
    lat: float = Field(..., ge=-90.0, le=90.0)
    lon: float = Field(..., ge=-180.0, le=180.0)

    @field_validator("lat", "lon")
    @classmethod
    def _finite(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("coordinates must be finite")
        return value


class ScoreRequest(BaseModel):
    transaction_id: str = Field(..., min_length=1)
    amount: float = Field(..., gt=0)
    payee_vpa: str = Field(..., min_length=1)
    user_id: str = Field(..., min_length=1)
    timestamp: datetime
    payer_location: PayerLocation | None = None
    is_new_payee: bool
    purpose: str | None = None
    device_id: str | None = None

    @field_validator("transaction_id", "payee_vpa", "user_id")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must be a non-empty string")
        return stripped

    @field_validator("purpose")
    @classmethod
    def _strip_purpose(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("amount")
    @classmethod
    def _finite_amount(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("amount must be a positive finite number")
        return value


class FeatureHit(BaseModel):
    name: str
    value: float


class ScoreResponse(BaseModel):
    transaction_id: str
    risk_score: float
    risk_tier: str
    P_xgb: float | None = None
    P_ae: float | None = None
    P_graph: float | None = None
    P_hybrid: float
    structuring_flag: bool | None = None
    ae_available: bool = False
    graph_available: bool = False
    structuring_available: bool = False
    top_contributing_features: list[FeatureHit]
    contributions: list[FeatureHit]
    action_required: bool
    canonical_decision: str | None = None
    canonical_risk_score: int | None = None
    action: str | None = None
    ml_available: bool | None = None
    challenge_id: str | None = None
    challenge_kind: str | None = None
    challenge_note: str | None = None
    ml_calibrated_for_upi: bool | None = None
    ml_evaluation: str | None = None
    score_components: dict[str, float] | None = None


class PrettyJSONResponse(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(content, indent=2, ensure_ascii=False, default=str).encode("utf-8")


class FeedLocation(BaseModel):
    status: str
    lat: float | None = None
    lon: float | None = None


class FeedPayment(BaseModel):
    id: str
    user_id: str
    amount: float
    currency: str = "INR"
    payee_vpa: str
    purpose: str | None = None
    timestamp: datetime
    location: FeedLocation


class FeedCanonical(BaseModel):
    """Engine decision. risk_score is 0–100. Values: ALLOW, REVIEW, BLOCK."""

    decision: str
    risk_score: int
    scale: str = "0-100"


class FeedPolicy(BaseModel):
    """UI action after canonical decision. legacy_score is 0–1. STEP_UP is policy, not a canonical value."""

    action: str
    legacy_tier: str
    legacy_score: float
    scale: str = "0-1"
    action_required: bool


class FeedModelSignal(BaseModel):
    """available is tri-state: true, false, or null if historical rows lack the field."""

    available: bool | None = None
    value: float | bool | None = None
    note: str | None = None


class FeedModels(BaseModel):
    xgboost: FeedModelSignal
    autoencoder: FeedModelSignal
    graph: FeedModelSignal
    structuring: FeedModelSignal


class FeedCase(BaseModel):
    payment: FeedPayment
    canonical: FeedCanonical
    policy: FeedPolicy
    models: FeedModels
    triggered_signals: list[FeatureHit]


class TransactionFeed(BaseModel):
    source: str = "GET /transactions"
    sandbox: bool = True
    count: int
    items: list[FeedCase]


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    model_version: str | None = None
    ml_fallback: str | None = None
    load_error: str | None = None
    open_sandbox: bool = False
    auth_warning: str | None = None
    ae_loaded: bool = False
    ae_error: str | None = None
    ae_note: str | None = None
    graph_available: bool = True
    graph_note: str | None = None
    ml_calibrated_for_upi: bool = False
    ml_evaluation: str | None = None
    ml_experimental: bool = False
    ml_note: str | None = None


class LoginRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class PinRequest(BaseModel):
    pin: str = Field(..., min_length=4, max_length=8)
    challenge_id: str | None = None


class RazorpayOrderRequest(BaseModel):
    amount: float = Field(..., gt=0)
    currency: str = "INR"
    receipt: str | None = None
    transaction_id: str | None = None

    @field_validator("amount")
    @classmethod
    def _finite_amount(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("amount must be a positive finite number")
        return value

    @field_validator("currency")
    @classmethod
    def _currency(cls, value: str) -> str:
        currency = value.strip().upper()
        if currency != "INR":
            raise ValueError("unsupported currency")
        return currency

    @field_validator("receipt", "transaction_id")
    @classmethod
    def _short_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        if len(stripped) > 128:
            raise ValueError("identifier too long")
        return stripped


def _cors_origins() -> list[str]:
    raw = os.getenv("SENTINALPAY_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    return [part.strip() for part in raw.split(",") if part.strip()]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    note = open_access_warning()
    if note:
        logger.warning(note)
    yield


app = FastAPI(title="SentinalPay Scoring API", version="1.0.0", lifespan=lifespan)
app.include_router(v1_router)
app.include_router(graphql_router, prefix="")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _feed_item(row: dict[str, Any]) -> FeedCase:
    raw = row.get("result_json")
    try:
        parsed = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        parsed = None
    result = parsed if isinstance(parsed, dict) else {
        "transaction_id": row["transaction_id"],
        "risk_score": row.get("risk_score") or 0,
        "decision": row.get("decision") or "REVIEW",
        "fraud_probability": row.get("fraud_probability") or 0.0,
        "rules": {"triggered_rules": []},
        "risk_factors": [],
    }
    fields = legacy_fields_from_canonical(result)
    ts = row["timestamp"]
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    lat = row.get("latitude")
    lon = row.get("longitude")
    ml = result.get("ml") if isinstance(result.get("ml"), dict) else {}
    ml_available = fields.get("ml_available")
    hits = [FeatureHit(**hit) for hit in fields["contributions"]]
    xgb_error = ml.get("error") if ml else None
    exp = result.get("experimental") if isinstance(result.get("experimental"), dict) else {}
    ae_available = fields.get("ae_available")
    graph_available = fields.get("graph_available")
    ae_note = exp.get("ae_error") or exp.get("note")
    if ae_available:
        ae_note = exp.get("note")
    graph_note = exp.get("note") if graph_available else (exp.get("graph_error") or "graph unavailable")
    if ml_available is True:
        xgb_note = None if ml.get("calibrated_for_upi") else "PaySim-trained; not a UPI-calibrated probability"
        xgb_value = fields.get("P_xgb")
    elif ml_available is False:
        xgb_value = None
        if xgb_error == "missing_file":
            xgb_note = "model file missing; fallback prior, not a live model score"
        elif xgb_error in {"load_error", "error"}:
            xgb_note = "model load failed; fallback prior, not a live model score"
        elif xgb_error == "incompatible":
            xgb_note = "incompatible model; fallback prior, not a live model score"
        elif xgb_error == "inference_error":
            xgb_note = "inference failed; fallback prior, not a live model score"
        else:
            xgb_note = "model unavailable; fallback prior, not a live model score"
    else:
        xgb_value = None
        xgb_note = "model availability unknown"
    return FeedCase(
        payment=FeedPayment(
            id=fields["transaction_id"],
            user_id=row["user_id"],
            amount=float(row["amount"]),
            payee_vpa=row.get("merchant_id") or "unknown_merchant",
            purpose=row.get("merchant_category"),
            timestamp=ts,
            location=FeedLocation(
                status="provided" if lat is not None and lon is not None else "omitted",
                lat=lat,
                lon=lon,
            ),
        ),
        canonical=FeedCanonical(
            decision=str(fields["canonical_decision"]),
            risk_score=int(fields["canonical_risk_score"] or 0),
        ),
        policy=FeedPolicy(
            action=str(fields.get("action") or fields["risk_tier"]),
            legacy_tier=str(fields["risk_tier"]),
            legacy_score=float(fields["risk_score"]),
            action_required=bool(fields["action_required"]),
        ),
        models=FeedModels(
            xgboost=FeedModelSignal(
                available=ml_available,
                value=xgb_value,
                note=xgb_note,
            ),
            autoencoder=FeedModelSignal(
                available=bool(ae_available),
                value=fields.get("P_ae"),
                note=str(ae_note) if ae_note else None,
            ),
            graph=FeedModelSignal(
                available=bool(graph_available),
                value=fields.get("P_graph"),
                note=str(graph_note) if graph_note else None,
            ),
            structuring=FeedModelSignal(
                available=bool(graph_available),
                value=fields.get("structuring_flag"),
                note=str(graph_note) if graph_note else None,
            ),
        ),
        triggered_signals=hits,
    )


@app.get("/")
def root() -> dict[str, str]:
    return {
        "service": "SentinalPay",
        "health": "/health",
        "graphql": "/graphql",
        "docs": "/docs",
        "score": "/score",
        "transactions": "/transactions",
        "evaluate": "/api/v1/transactions/evaluate",
        "ready": "/ready",
        "admin_login": "/admin/login",
    }


@app.get("/ready")
def ready() -> dict[str, Any]:
    """Process can accept traffic. Model missing is still ready (fail-closed on ALLOW)."""
    store_ok = True
    try:
        get_store().count_transactions()
    except Exception:
        store_ok = False
    status = model_status()
    return {
        "ready": store_ok,
        "store": store_ok,
        "model_loaded": bool(status.get("model_loaded")),
        "model_version": status.get("model_version"),
    }


def _ae_health() -> dict[str, Any]:
    try:
        from detection.autoencoder_scorer import ae_status

        return ae_status()
    except Exception:
        return {
            "ae_loaded": False,
            "ae_error": "status_error",
            "ae_note": "fused after the primary score; not a term in R",
        }


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    ae = _ae_health()
    graph_note = "windowed store heuristic (24h, cap 2000); fused after the primary score, not a term in R"
    try:
        status = model_status()
    except Exception:
        return HealthResponse(
            status="ok",
            model_loaded=False,
            model_version="error",
            ml_fallback="conservative_prior_0.5; ALLOW demoted to REVIEW",
            load_error="status_error",
            open_sandbox=not require_login(),
            auth_warning=open_access_warning(),
            ae_loaded=bool(ae.get("ae_loaded")),
            ae_error=ae.get("ae_error"),
            ae_note=ae.get("ae_note"),
            graph_available=True,
            graph_note=graph_note,
            ml_calibrated_for_upi=False,
            ml_evaluation=None,
            ml_experimental=False,
            ml_note=None,
        )
    return HealthResponse(
        status="ok",
        model_loaded=status["model_loaded"],
        model_version=status["model_version"],
        ml_fallback=status["ml_fallback"],
        load_error=status.get("load_error"),
        open_sandbox=not require_login(),
        auth_warning=open_access_warning(),
        ae_loaded=bool(ae.get("ae_loaded")),
        ae_error=ae.get("ae_error"),
        ae_note=ae.get("ae_note"),
        graph_available=True,
        graph_note=graph_note,
        ml_calibrated_for_upi=bool(status.get("calibrated_for_upi")),
        ml_evaluation=status.get("evaluation"),
        ml_experimental=bool(status.get("experimental")),
        ml_note=status.get("note"),
    )


@app.post("/login")
def login(payload: LoginRequest, request: Request) -> dict[str, Any]:
    store = get_store()
    user_id = payload.user_id.strip()
    throttle = login_throttle_key(user_id, request)
    assert_login_not_locked(store, throttle)
    if not store.verify_login(user_id, payload.password):
        note_login_failure(store, throttle)
        raise HTTPException(status_code=401, detail="invalid credentials")
    token = store.create_session(user_id)
    return {"token": token, "user_id": user_id}


@app.post("/logout")
def logout(request: Request) -> dict[str, Any]:
    return logout_request(request)


class AdminLoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


@app.post("/admin/login")
def admin_login(payload: AdminLoginRequest, request: Request, response: Response) -> dict[str, Any]:
    store = get_store()
    username = payload.username.strip()
    throttle = login_throttle_key(f"admin:{username}", request)
    assert_login_not_locked(store, throttle)
    if not store.verify_admin(username, payload.password):
        note_login_failure(store, throttle)
        raise HTTPException(status_code=401, detail="invalid credentials")
    token = store.create_session(username, kind="admin")
    apply_admin_cookie(response, token)
    return {"ok": True, "username": username}


@app.post("/admin/logout")
def admin_logout(request: Request, response: Response) -> dict[str, Any]:
    require_admin_session(request)
    require_admin_csrf(request)
    token = (request.cookies.get("sp_admin") or "").strip()
    if token:
        get_store().revoke_session(token)
    clear_admin_cookie(response)
    return {"ok": True}


@app.get("/admin/session")
def admin_session(request: Request) -> dict[str, str]:
    return {"username": require_admin_session(request)}


@app.post("/pin/verify")
def verify_pin(payload: PinRequest, request: Request) -> dict[str, Any]:
    return verify_pin_request(request, payload.pin, payload.challenge_id)


@app.post("/score", response_model=ScoreResponse)
def score(payload: ScoreRequest, request: Request) -> ScoreResponse:
    client_key = protect_sensitive(request)
    if require_login():
        session_user = require_session(request)
        if session_user != payload.user_id:
            raise HTTPException(status_code=403, detail="user mismatch")
    try:
        result = evaluate_transaction(
            pipeline_payload_from_score(payload.model_dump()),
            client_key=client_key,
            session_token=bearer_token(request),
        )
    except PipelineError as exc:
        raise HTTPException(status_code=http_status_for_pipeline_error(exc), detail=str(exc)) from exc
    fields = legacy_fields_from_canonical(result)
    logger.info(
        "transaction_id=%s account=%s canonical=%s legacy=%s score=%s",
        payload.transaction_id,
        mask_identifier(payload.user_id),
        result.get("decision"),
        fields["risk_tier"],
        result.get("risk_score"),
    )
    return ScoreResponse(
        **{
            **fields,
            "top_contributing_features": [FeatureHit(**hit) for hit in fields["top_contributing_features"]],
            "contributions": [FeatureHit(**hit) for hit in fields["contributions"]],
            "challenge_id": result.get("challenge_id"),
            "challenge_kind": result.get("challenge_kind"),
            "challenge_note": result.get("challenge_note"),
        }
    )


@app.post("/webhooks/razorpay")
async def razorpay_webhook(request: Request) -> dict[str, Any]:
    adapter = get_razorpay_adapter()
    if not adapter.webhook_secret:
        raise HTTPException(status_code=503, detail="RAZORPAY_WEBHOOK_SECRET not configured")
    body = await read_body_capped(request, webhook_max_bytes())
    outcome = adapter.ingest_event(
        body=body,
        signature=request.headers.get("X-Razorpay-Signature"),
        headers={k: v for k, v in request.headers.items()},
        ledger=get_store(),
    )
    if not outcome.get("accepted"):
        raise HTTPException(status_code=401, detail=str(outcome.get("error") or "rejected"))
    return outcome


@app.post("/payments/razorpay/orders")
def razorpay_order(payload: RazorpayOrderRequest, request: Request) -> dict[str, Any]:
    require_order_auth(request)
    adapter = get_razorpay_adapter()
    receipt = payload.receipt or payload.transaction_id or "demo"
    try:
        ref = adapter.create_or_reference(
            amount=payload.amount,
            currency=payload.currency,
            receipt=receipt,
            notes={"transaction_id": payload.transaction_id or ""},
        )
    except RazorpayConfigError as exc:
        text = str(exc).lower()
        if "required" in text:
            raise HTTPException(status_code=503, detail="razorpay not configured") from exc
        raise HTTPException(status_code=502, detail="provider_unavailable") from exc
    return {
        "provider": ref.provider,
        "id": ref.provider_payment_id,
        "status": ref.status,
        "amount": ref.amount,
        "currency": ref.currency,
        "note": "advisory scoring only; Razorpay still authorizes. Redirect is not success.",
    }


class CheckoutOrderRequest(BaseModel):
    amount: int = Field(..., gt=0)
    currency: str = "INR"
    transaction_id: str = ""
    user_id: str = ""
    merchant_id: str | None = None
    payee_vpa: str | None = None
    merchant_category: str | None = None
    purpose: str | None = None
    device_id: str | None = None
    timestamp: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    receipt: str | None = None

    @field_validator("currency")
    @classmethod
    def _inr(cls, value: str) -> str:
        currency = value.strip().upper()
        if currency != "INR":
            raise ValueError("unsupported currency")
        return currency

    @field_validator("receipt", "transaction_id", "user_id")
    @classmethod
    def _short(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str = ""
    razorpay_payment_id: str = ""
    razorpay_signature: str = ""
    transaction_id: str = ""


def _raise_razorpay(exc: Exception) -> None:
    if isinstance(exc, RazorpayApiError):
        if exc.status == 401:
            raise HTTPException(status_code=401, detail="razorpay auth failed") from exc
        raise HTTPException(status_code=500, detail="razorpay request failed") from exc
    text = str(exc).lower()
    if "required" in text:
        raise HTTPException(status_code=503, detail="razorpay not configured") from exc
    raise HTTPException(status_code=500, detail="razorpay request failed") from exc


def _require_checkout_auth(request: Request) -> str | None:
    """Open sandbox can pay. Login mode and a presented session still bind the payer.

    Risk policy stays on the server either way. `/payments/razorpay/orders` keeps require_order_auth.
    """
    if os.getenv("SENTINALPAY_API_KEY", "").strip():
        authenticate_request(request)
    if require_login():
        return require_session(request)
    token = bearer_token(request)
    if not token:
        return None
    user_id = get_store().session_user(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="invalid session")
    return user_id


def _checkout_allowed(store: Any, result: dict[str, Any], user_id: str) -> bool:
    """ALLOW, or a consumed STEP_UP challenge. HOLD is resolved separately. BLOCK never pays."""
    action = str(result.get("action") or "HOLD")
    transaction_id = str(result.get("transaction_id") or "")
    if action == "ALLOW":
        return True
    if action == "STEP_UP":
        return store.challenge_cleared(transaction_id, user_id)
    return False


def _checkout_fields(payload: CheckoutOrderRequest, user_id: str, merchant: str) -> dict[str, Any]:
    return {
        "transaction_id": payload.transaction_id or "",
        "user_id": user_id,
        "amount_paise": payload.amount,
        "currency": payload.currency,
        "merchant_id": merchant,
        "device_id": payload.device_id or "",
        "latitude": payload.latitude,
        "longitude": payload.longitude,
        "timestamp": payload.timestamp,
    }


def _public_secondary(resolved: dict[str, Any]) -> str:
    """Expired approval does not stay payable and does not become a new approval."""
    outcome = str(resolved.get("outcome") or "CONTINUE_HOLD")
    if outcome not in {"APPROVE", "REJECT", "CONTINUE_HOLD", "STEP_UP"}:
        return "CONTINUE_HOLD"
    if resolved.get("expired") and outcome in {"APPROVE", "STEP_UP"}:
        return "CONTINUE_HOLD"
    return outcome


def _deny_hold(result: dict[str, Any], resolved: dict[str, Any], transaction_id: str) -> None:
    raise HTTPException(
        status_code=403,
        detail={
            "action": "HOLD",
            "decision": result.get("decision"),
            "risk_score": result.get("risk_score"),
            "transaction_id": transaction_id,
            "secondary_outcome": _public_secondary(resolved),
        },
    )


def _checkout_body(
    row: dict[str, Any],
    result: dict[str, Any] | None = None,
    secondary_outcome: str | None = None,
) -> dict[str, Any]:
    scored = result or {}
    status = str(row.get("payment_status") or "none")
    body = {
        "order_id": row.get("order_id"),
        "amount": int(row["amount_paise"]),
        "currency": row["currency"],
        "transaction_id": row["transaction_id"],
        "action": scored.get("action"),
        "decision": scored.get("decision"),
        "risk_score": scored.get("risk_score"),
        "payment_status": status,
        "settled": status == "captured",
    }
    if secondary_outcome:
        body["secondary_outcome"] = secondary_outcome
    return body


def _replay_checkout(store: Any, row: dict[str, Any], fields: dict[str, Any]) -> dict[str, Any]:
    """Same transaction returns its order only when the bound details still match."""
    transaction_id = str(row["transaction_id"])
    secondary = store.get_secondary_assessment(transaction_id)
    result = store.get_result(transaction_id) or {}
    if secondary is None:
        return _checkout_body(row, result)
    if not same_binding(secondary, fields):
        raise HTTPException(status_code=409, detail="transaction details changed")
    public = _public_secondary(secondary)
    if public not in {"APPROVE", "STEP_UP"}:
        if not result:
            result = {
                "decision": secondary.get("primary_decision"),
                "risk_score": secondary.get("primary_score"),
            }
        _deny_hold(result, secondary, transaction_id)
    if not result.get("action"):
        result = {
            **result,
            "action": secondary.get("primary_action"),
            "decision": secondary.get("primary_decision"),
            "risk_score": secondary.get("primary_score"),
        }
    return _checkout_body(row, result, public)


@app.post("/api/create-order")
def create_checkout_order(payload: CheckoutOrderRequest, request: Request) -> dict[str, Any]:
    """Score, then create one Razorpay order only when policy allows it.

    Amount is paise. The browser does not decide ALLOW, HOLD, STEP_UP, or BLOCK.
    """
    if payload.amount < 100:
        raise HTTPException(status_code=400, detail="minimum amount is 100 paise")
    session_user = _require_checkout_auth(request)
    transaction_id = payload.transaction_id or ""
    user_id = payload.user_id or ""
    merchant = (payload.merchant_id or payload.payee_vpa or "").strip()
    if not transaction_id or not user_id or not merchant:
        raise HTTPException(status_code=400, detail="missing fields")
    if session_user and session_user != user_id:
        raise HTTPException(status_code=403, detail="user mismatch")
    store = get_store()
    claim = store.begin_checkout_order(
        transaction_id=transaction_id,
        user_id=user_id,
        amount_paise=payload.amount,
        currency=payload.currency,
    )
    if claim.get("conflict"):
        raise HTTPException(status_code=409, detail="transaction already used")
    if claim.get("in_progress"):
        raise HTTPException(status_code=409, detail="order in progress")
    row = claim["row"]
    fields = _checkout_fields(payload, user_id, merchant)
    if row.get("order_id"):
        return _replay_checkout(store, row, fields)
    rupees = round(payload.amount / 100, 2)
    raw: dict[str, Any] = {
        "transaction_id": transaction_id,
        "user_id": user_id,
        "amount": rupees,
        "currency": payload.currency,
        "merchant_id": merchant,
        "merchant_category": payload.merchant_category or payload.purpose,
        "device_id": payload.device_id,
        "timestamp": payload.timestamp,
    }
    if payload.latitude is not None and payload.longitude is not None:
        raw["latitude"] = payload.latitude
        raw["longitude"] = payload.longitude
    try:
        result = evaluate_transaction(raw, session_token=bearer_token(request))
    except PipelineError as exc:
        store.release_checkout_order(transaction_id)
        raise HTTPException(status_code=http_status_for_pipeline_error(exc), detail=str(exc)) from exc
    secondary_outcome = None
    if str(result.get("action") or "") == "HOLD":
        resolved = resolve_hold(store, result, fields)
        if resolved.get("conflict"):
            store.release_checkout_order(transaction_id)
            raise HTTPException(status_code=409, detail="transaction details changed")
        public = _public_secondary(resolved)
        if public == "STEP_UP":
            if not store.challenge_cleared(transaction_id, user_id):
                challenge = store.create_challenge(user_id, transaction_id, bearer_token(request))
                store.release_checkout_order(transaction_id)
                raise HTTPException(
                    status_code=403,
                    detail={
                        "action": "STEP_UP",
                        "decision": result.get("decision"),
                        "risk_score": result.get("risk_score"),
                        "challenge_id": challenge.get("challenge_id"),
                        "transaction_id": transaction_id,
                        "secondary_outcome": "STEP_UP",
                    },
                )
            secondary_outcome = "STEP_UP"
        elif public != "APPROVE":
            store.release_checkout_order(transaction_id)
            _deny_hold(result, resolved, transaction_id)
        else:
            secondary_outcome = "APPROVE"
    elif not _checkout_allowed(store, result, user_id):
        store.release_checkout_order(transaction_id)
        raise HTTPException(
            status_code=403,
            detail={
                "action": result.get("action"),
                "decision": result.get("decision"),
                "risk_score": result.get("risk_score"),
                "challenge_id": result.get("challenge_id"),
                "transaction_id": result.get("transaction_id") or transaction_id,
            },
        )
    adapter = get_razorpay_adapter()
    try:
        created = adapter.create_order_paise(
            amount_paise=payload.amount,
            currency=payload.currency,
            receipt=(payload.receipt or transaction_id)[:40],
            notes={"transaction_id": transaction_id},
        )
    except (RazorpayApiError, RazorpayConfigError) as exc:
        store.release_checkout_order(transaction_id)
        _raise_razorpay(exc)
        raise
    if int(created.get("amount") or 0) != payload.amount or str(created.get("currency") or "") != payload.currency:
        store.release_checkout_order(transaction_id)
        raise HTTPException(status_code=502, detail="provider amount mismatch")
    store.attach_checkout_order(transaction_id, str(created["order_id"]))
    saved = store.get_checkout_by_transaction(transaction_id) or row
    saved["order_id"] = created["order_id"]
    saved["amount_paise"] = payload.amount
    return _checkout_body(saved, result, secondary_outcome)


def _verify_body(row: dict[str, Any]) -> dict[str, Any]:
    status = str(row.get("payment_status") or "none")
    return {
        "ok": status in {"authorized", "captured"},
        "settled": status == "captured",
        "payment_status": status,
        "transaction_id": row.get("transaction_id"),
        "order_id": row.get("order_id"),
    }


@app.post("/api/verify-payment")
def verify_checkout_payment(payload: VerifyPaymentRequest, request: Request) -> dict[str, Any]:
    """Signature plus the provider's own status. A signature is not a capture."""
    session_user = _require_checkout_auth(request)
    order_id = payload.razorpay_order_id.strip()
    payment_id = payload.razorpay_payment_id.strip()
    signature = payload.razorpay_signature.strip()
    if not order_id or not payment_id or not signature:
        raise HTTPException(status_code=400, detail="missing fields")
    store = get_store()
    row = store.get_checkout_order(order_id)
    if row is None:
        raise HTTPException(status_code=400, detail="order mismatch")
    if payload.transaction_id.strip() and payload.transaction_id.strip() != row["transaction_id"]:
        raise HTTPException(status_code=400, detail="order mismatch")
    if session_user and session_user != row["user_id"]:
        raise HTTPException(status_code=403, detail="user mismatch")
    adapter = get_razorpay_adapter()
    if not adapter.verify_checkout_signature(order_id, payment_id, signature):
        raise HTTPException(status_code=400, detail="signature mismatch")
    if row.get("payment_id") == payment_id and str(row.get("payment_status") or "none") not in {"none", ""}:
        return _verify_body(row)
    try:
        ref = adapter.fetch_status(payment_id, ledger=store)
    except (RazorpayApiError, RazorpayConfigError) as exc:
        _raise_razorpay(exc)
        raise
    if str(ref.order_id or "") != order_id:
        raise HTTPException(status_code=400, detail="order mismatch")
    if int(round(float(ref.amount) * 100)) != int(row["amount_paise"]):
        raise HTTPException(status_code=400, detail="amount mismatch")
    if str(ref.currency or "").upper() != str(row["currency"]):
        raise HTTPException(status_code=400, detail="currency mismatch")
    store.sync_checkout_payment(
        order_id=order_id,
        payment_id=payment_id,
        status=str(ref.status or "unknown"),
        amount=float(ref.amount),
        currency=str(ref.currency or row["currency"]),
    )
    fresh = store.get_checkout_order(order_id) or row
    return _verify_body(fresh)


@app.get("/transactions", response_model=TransactionFeed, response_class=PrettyJSONResponse)
def transactions(request: Request, limit: int = Query(default=50, ge=1, le=200)) -> TransactionFeed:
    """Newest-first sandbox desk feed. Admin cookie required even when payer login is off."""
    protect_sensitive(request)
    require_admin_session(request)
    cap = min(limit, max(10, int(os.getenv("SENTINALPAY_FEED_MAX", "100"))))
    items = [_feed_item(row) for row in get_store().recent_evaluations(cap)]
    return TransactionFeed(count=len(items), items=items)
