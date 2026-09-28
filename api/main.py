"""FastAPI scoring service.

POST /score         — payment app submits a txn; returns hybrid risk
GET  /transactions  — fraud desk polls the live scored feed
GET  /health        — process + model liveness

Scoring itself is a pure function of (payload, that user's history snapshot,
the model). The feed/history append happens after the score is computed.

# TODO: apply rate limiting here before production use
# TODO: persist via parameterized queries / ORM only — never string-formatted SQL
"""

from __future__ import annotations

import logging
import os
from collections import deque
from datetime import datetime, timedelta, timezone
from math import isfinite
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from detection.autoencoder_scorer import score_autoencoder
from detection.graph_features import (
    GraphValidationError,
    add_transaction,
    empty_graph,
    graph_signals,
    score_graph,
)
from detection.privacy import mask_identifier
from detection.scoring_engine import FEATURE_VECTOR_NAMES, extract_feature_vector
from detection.validation import ScoringValidationError

load_dotenv()

logger = logging.getLogger("sentinalpay.api")
logging.basicConfig(level=os.getenv("SENTINALPAY_LOG_LEVEL", "INFO"))

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = REPO_ROOT / "ml" / "models" / "xgboost_model.pkl"

# API risk-tier cutovers (inclusive-upper via `<` checks). Distinct from the
# rule-engine cutovers in detection.constants — this is the live ML gate.
ALLOW_LT = 0.35
STEP_UP_LT = 0.60
HOLD_LT = 0.82

# Pune — matches the consumer-app demo home corridor.
_HOME = (18.5204, 73.8567)


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


def _model_path() -> Path:
    override = os.getenv("SENTINALPAY_XGB_MODEL", "").strip()
    if not override:
        return DEFAULT_MODEL
    path = Path(override)
    return path if path.is_absolute() else REPO_ROOT / path


def _load_model() -> Any:
    path = _model_path()
    if not path.exists():
        logger.warning("model missing at startup path_set=1")
        return None
    loaded = joblib.load(path)
    if isinstance(loaded, dict) and "model" in loaded:
        return loaded["model"]
    return loaded


def _seed_history() -> dict[str, list[dict[str, Any]]]:
    """In-memory stand-in for a user ledger. Replace with a DB later."""
    now = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
    payees = (
        "priya.p@oksbi",
        "zomato@icici",
        "kirana.pune@oksbi",
    )
    amounts = (180.0, 420.0, 95.0, 350.0, 240.0, 510.0, 160.0, 890.0)
    rows: list[dict[str, Any]] = []
    for i, amount in enumerate(amounts):
        rows.append(
            {
                "transaction_id": f"seed_{i:02d}",
                "user_id": "aarav@senitenial",
                "amount": amount,
                "payee_vpa": payees[i % len(payees)],
                "timestamp": now - timedelta(days=14 - i, hours=i),
                "lat": _HOME[0] + 0.002 * ((-1) ** i),
                "lon": _HOME[1] + 0.002 * ((-1) ** i),
            }
        )
    return {"aarav@senitenial": rows}


def _tier_for(probability: float) -> str:
    if probability < ALLOW_LT:
        return "ALLOW"
    if probability < STEP_UP_LT:
        return "STEP_UP"
    if probability < HOLD_LT:
        return "HOLD"
    return "BLOCK"


def _top_features(vector: dict[str, float], model: Any) -> list[FeatureHit]:
    importances = getattr(model, "feature_importances_", None)
    ranked: list[tuple[float, str, float]] = []
    for i, name in enumerate(FEATURE_VECTOR_NAMES):
        value = float(vector.get(name, 0.0))
        weight = float(importances[i]) if importances is not None and i < len(importances) else 0.0
        ranked.append((value * weight if weight else value, name, value))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [FeatureHit(name=name, value=value) for _, name, value in ranked[:5]]


def score_request(payload: ScoreRequest, history: list[dict[str, Any]], model: Any) -> ScoreResponse:
    """Stateless scorer: same inputs always produce the same output."""
    txn = {
        "transaction_id": payload.transaction_id,
        "user_id": payload.user_id,
        "amount": payload.amount,
        "payee_vpa": payload.payee_vpa,
        "timestamp": payload.timestamp,
        "lat": payload.payer_location.lat,
        "lon": payload.payer_location.lon,
    }
    known = {item["payee_vpa"] for item in history}
    if payload.is_new_payee:
        known.discard(payload.payee_vpa)
    else:
        known.add(payload.payee_vpa)
    profile = {
        "user_id": payload.user_id,
        "home_lat": _HOME[0],
        "home_lon": _HOME[1],
        "known_payees": known,
    }
    try:
        vector = extract_feature_vector(txn, history, profile)
    except ScoringValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    x = np.asarray([[vector[name] for name in FEATURE_VECTOR_NAMES]], dtype=np.float32)
    p_xgb = float(model.predict_proba(x)[0, 1])
    p_ae = score_autoencoder(vector)
    try:
        add_transaction(TXN_GRAPH, txn)
    except GraphValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    p_graph = score_graph(TXN_GRAPH, payload.user_id)
    signals = graph_signals(TXN_GRAPH, payload.user_id)
    # Placeholder weights pending Bayesian optimisation on a validation set.
    p_hybrid = max(0.0, min(1.0, 0.5 * p_xgb + 0.3 * p_ae + 0.2 * p_graph))

    risk_score = p_hybrid
    risk_tier = _tier_for(risk_score)
    logger.info(
        "transaction_id=%s account=%s P_xgb=%.4f P_ae=%.4f P_graph=%.4f P_hybrid=%.4f",
        payload.transaction_id,
        mask_identifier(payload.user_id),
        p_xgb,
        p_ae,
        p_graph,
        p_hybrid,
    )
    hits = [FeatureHit(name=name, value=float(vector.get(name, 0.0))) for name in FEATURE_VECTOR_NAMES]
    return ScoreResponse(
        transaction_id=payload.transaction_id,
        risk_score=risk_score,
        risk_tier=risk_tier,
        P_xgb=p_xgb,
        P_ae=p_ae,
        P_graph=p_graph,
        P_hybrid=p_hybrid,
        structuring_flag=bool(signals["structuring_flag"]),
        top_contributing_features=_top_features(vector, model),
        contributions=hits,
        action_required=risk_tier != "ALLOW",
    )


app = FastAPI(title="SentinalPay Scoring API", version="0.5.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MODEL = _load_model()
USER_HISTORY: dict[str, list[dict[str, Any]]] = _seed_history()
_FEED_MAX = max(10, int(os.getenv("SENTINALPAY_FEED_MAX", "100")))
# Live scored payments from the app. Process-local — swap for a DB later.
SCORED_FEED: deque[FeedItem] = deque(maxlen=_FEED_MAX)
# In-memory MultiDiGraph for the demo. Move to a graph DB / persistent
# store before production use — this process loses the graph on restart.
TXN_GRAPH = empty_graph()
for _rows in USER_HISTORY.values():
    for _row in _rows:
        try:
            add_transaction(TXN_GRAPH, _row)
        except GraphValidationError:
            continue


def _history_row(payload: ScoreRequest) -> dict[str, Any]:
    return {
        "transaction_id": payload.transaction_id,
        "user_id": payload.user_id,
        "amount": payload.amount,
        "payee_vpa": payload.payee_vpa,
        "timestamp": payload.timestamp,
        "lat": payload.payer_location.lat,
        "lon": payload.payer_location.lon,
        "purpose": payload.purpose,
    }


def _remember(payload: ScoreRequest, result: ScoreResponse) -> None:
    """Append after scoring so the current request stays a snapshot."""
    rows = USER_HISTORY.setdefault(payload.user_id, [])
    rows.append(_history_row(payload))
    if len(rows) > 200:
        del rows[:-200]
    SCORED_FEED.appendleft(
        FeedItem(
            **result.model_dump(),
            user_id=payload.user_id,
            amount=payload.amount,
            payee_vpa=payload.payee_vpa,
            timestamp=payload.timestamp,
            lat=payload.payer_location.lat,
            lon=payload.payer_location.lon,
            purpose=payload.purpose,
        )
    )


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", model_loaded=MODEL is not None)


@app.post("/score", response_model=ScoreResponse)
def score(payload: ScoreRequest) -> ScoreResponse:
    if MODEL is None:
        raise HTTPException(status_code=503, detail="model not loaded")
    history = list(USER_HISTORY.get(payload.user_id, ()))
    result = score_request(payload, history, MODEL)
    _remember(payload, result)
    return result


@app.get("/transactions", response_model=list[FeedItem])
def transactions(limit: int = Query(default=50, ge=1, le=200)) -> list[FeedItem]:
    """Newest-first live feed for the fraud desk."""
    return list(SCORED_FEED)[:limit]
