"""HTTP adapter. Scoring lives in risk.pipeline — not here.

POST /score                         — React REST contract (kept)
POST /graphql                       — same engine, GraphQL query/mutation
POST /api/v1/transactions/evaluate  — canonical REST contract
GET  /transactions                  — desk feed
GET  /health

# TODO: apply rate limiting here before production use
# TODO: persist via parameterized queries / ORM only — never string-formatted SQL
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from math import isfinite
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from api.compat import legacy_fields_from_canonical, pipeline_payload_from_score
from api.graphql import graphql_router
from api.v1 import router as v1_router
from detection.privacy import mask_identifier
from risk.auth import require_login, require_session
from risk.ml_layer import model_status
from risk.pipeline import PipelineError, evaluate_transaction
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
    P_xgb: float
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
    available: bool
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


class LoginRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class PinRequest(BaseModel):
    pin: str = Field(..., min_length=4, max_length=8)


def _cors_origins() -> list[str]:
    raw = os.getenv("SENTINALPAY_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    return [part.strip() for part in raw.split(",") if part.strip()]


app = FastAPI(title="SentinalPay Scoring API", version="1.0.0")
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
    if ml_available is None:
        ml_available = bool(ml.get("available")) if ml else None
    hits = [FeatureHit(**hit) for hit in fields["contributions"]]
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
                available=ml_available is not False,
                value=fields["P_xgb"],
                note="fallback prior, not a live model score" if ml_available is False else None,
            ),
            autoencoder=FeedModelSignal(
                available=False,
                value=None,
                note="component not wired",
            ),
            graph=FeedModelSignal(
                available=False,
                value=None,
                note="component not wired",
            ),
            structuring=FeedModelSignal(
                available=False,
                value=None,
                note="component not wired",
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
    }


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    status = model_status()
    return HealthResponse(
        status="ok",
        model_loaded=status["model_loaded"],
        model_version=status["model_version"],
        ml_fallback=status["ml_fallback"],
    )


@app.post("/login")
def login(payload: LoginRequest) -> dict[str, Any]:
    store = get_store()
    if not store.verify_login(payload.user_id.strip(), payload.password):
        raise HTTPException(status_code=401, detail="invalid credentials")
    token = store.create_session(payload.user_id.strip())
    return {"token": token, "user_id": payload.user_id.strip()}


@app.post("/pin/verify")
def verify_pin(payload: PinRequest, request: Request) -> dict[str, Any]:
    user_id = require_session(request)
    if not get_store().verify_pin(user_id, payload.pin):
        raise HTTPException(status_code=401, detail="invalid pin")
    return {"ok": True}


@app.post("/score", response_model=ScoreResponse)
def score(payload: ScoreRequest, request: Request) -> ScoreResponse:
    if require_login():
        session_user = require_session(request)
        if session_user != payload.user_id:
            raise HTTPException(status_code=403, detail="user mismatch")
    try:
        result = evaluate_transaction(pipeline_payload_from_score(payload.model_dump()), client_key=payload.user_id)
    except PipelineError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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
        }
    )


@app.get("/transactions", response_model=TransactionFeed, response_class=PrettyJSONResponse)
def transactions(limit: int = Query(default=50, ge=1, le=200)) -> TransactionFeed:
    """Newest-first sandbox desk feed. Nested so payment, decision, and models stay distinct."""
    cap = min(limit, max(10, int(os.getenv("SENTINALPAY_FEED_MAX", "100"))))
    items = [_feed_item(row) for row in get_store().recent_evaluations(cap)]
    return TransactionFeed(count=len(items), items=items)
