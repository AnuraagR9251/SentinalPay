"""Versioned risk API. Routes call the pipeline — they do not score."""

from __future__ import annotations

from datetime import datetime
from math import isfinite
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from risk.auth import authenticate_request, bearer_token, require_login, require_session
from risk.pipeline import PipelineError, evaluate_transaction, http_status_for_pipeline_error
from risk.store import get_store

router = APIRouter(prefix="/api/v1", tags=["risk-v1"])


class EvaluateRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    amount: float = Field(..., gt=0)
    currency: str = "INR"
    merchant_id: str | None = None
    merchant_category: str | None = None
    transaction_id: str | None = None
    timestamp: datetime | None = None
    device_id: str | None = None
    ip_address: str | None = None
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)
    recent_failures: int = Field(default=0, ge=0)

    @field_validator("user_id", "currency")
    @classmethod
    def _strip(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must be non-empty")
        return stripped

    @field_validator("amount")
    @classmethod
    def _finite_amount(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("amount must be finite")
        return value


class ReviewRequest(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]
    reason: str = Field(..., min_length=1)


@router.post("/transactions/evaluate")
def evaluate(payload: EvaluateRequest, request: Request, client_key: str = Depends(authenticate_request)) -> dict[str, Any]:
    if require_login():
        session_user = require_session(request)
        if session_user != payload.user_id:
            raise HTTPException(status_code=403, detail="user mismatch")
    try:
        result = evaluate_transaction(
            payload.model_dump(),
            client_key=client_key,
            session_token=bearer_token(request),
        )
    except PipelineError as exc:
        raise HTTPException(status_code=http_status_for_pipeline_error(exc), detail=str(exc)) from exc
    return result


@router.post("/reviews/{transaction_id}")
def review(
    transaction_id: str,
    payload: ReviewRequest,
    _key: str = Depends(authenticate_request),
) -> dict[str, Any]:
    try:
        return get_store().submit_review(transaction_id.strip(), payload.decision, payload.reason.strip())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="review case not found") from exc


@router.get("/reviews")
def reviews(status: str = "PENDING", _key: str = Depends(authenticate_request)) -> list[dict[str, Any]]:
    if status != "PENDING":
        return []
    return get_store().pending_reviews()
