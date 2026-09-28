"""HTTP adapter. Scoring lives in risk.pipeline — not here.

POST /score                         — React contract (0–1, ALLOW/HOLD/BLOCK)
POST /api/v1/transactions/evaluate  — canonical contract (0–100, ALLOW/REVIEW/BLOCK)
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
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from api.compat import legacy_fields_from_canonical, pipeline_payload_from_score
from api.v1 import router as v1_router
from detection.privacy import mask_identifier
from risk.ml_layer import model_is_loaded
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
    payer_location: PayerLocation
    is_new_payee: bool
    purpose: str | None = None

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
    P_ae: float
    P_graph: float
    P_hybrid: float
    structuring_flag: bool
    top_contributing_features: list[FeatureHit]
    contributions: list[FeatureHit]
    action_required: bool
    canonical_decision: str | None = None
    canonical_risk_score: int | None = None


class FeedItem(ScoreResponse):
    """One live payment as stored for GET /transactions."""

    user_id: str
    amount: float
    payee_vpa: str
    timestamp: datetime
    lat: float | None = None
    lon: float | None = None
    purpose: str | None = None


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool


def _cors_origins() -> list[str]:
    raw = os.getenv("SENTINALPAY_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    return [part.strip() for part in raw.split(",") if part.strip()]


app = FastAPI(title="SentinalPay Scoring API", version="1.0.0")
app.include_router(v1_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _feed_item(row: dict[str, Any]) -> FeedItem:
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
    return FeedItem(
        transaction_id=fields["transaction_id"],
        risk_score=fields["risk_score"],
        risk_tier=fields["risk_tier"],
        P_xgb=fields["P_xgb"],
        P_ae=fields["P_ae"],
        P_graph=fields["P_graph"],
        P_hybrid=fields["P_hybrid"],
        structuring_flag=fields["structuring_flag"],
        top_contributing_features=[FeatureHit(**hit) for hit in fields["top_contributing_features"]],
        contributions=[FeatureHit(**hit) for hit in fields["contributions"]],
        action_required=fields["action_required"],
        canonical_decision=fields["canonical_decision"],
        canonical_risk_score=fields["canonical_risk_score"],
        user_id=row["user_id"],
        amount=float(row["amount"]),
        payee_vpa=row.get("merchant_id") or "unknown_merchant",
        timestamp=ts,
        lat=row.get("latitude"),
        lon=row.get("longitude"),
        purpose=row.get("merchant_category"),
    )


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", model_loaded=model_is_loaded())


@app.post("/score", response_model=ScoreResponse)
def score(payload: ScoreRequest) -> ScoreResponse:
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


@app.get("/transactions", response_model=list[FeedItem])
def transactions(limit: int = Query(default=50, ge=1, le=200)) -> list[FeedItem]:
    """Newest-first desk feed from the canonical RiskStore."""
    cap = min(limit, max(10, int(os.getenv("SENTINALPAY_FEED_MAX", "100"))))
    return [_feed_item(row) for row in get_store().recent_evaluations(cap)]
