"""GraphQL adapter. Same pipeline as REST — no second scoring engine."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import strawberry
from fastapi import HTTPException, Request
from strawberry.fastapi import GraphQLRouter
from strawberry.scalars import JSON
from strawberry.types import Info

from api.compat import legacy_fields_from_canonical, pipeline_payload_from_score
from detection.privacy import mask_identifier
from risk.auth import (
    assert_login_not_locked,
    bearer_token,
    login_throttle_key,
    note_login_failure,
    require_login,
    require_session,
)
from risk.ml_layer import model_status
from risk.pipeline import PipelineError
from risk.pipeline import evaluate_transaction as run_pipeline
from risk.store import get_store


@strawberry.type
class FeatureHit:
    name: str
    value: float


@strawberry.type
class HealthPayload:
    status: str
    model_loaded: bool
    model_version: Optional[str] = None
    ml_fallback: Optional[str] = None


@strawberry.type
class ScorePayload:
    transaction_id: str
    risk_score: float
    risk_tier: str
    p_xgb: Optional[float] = None
    p_ae: Optional[float] = None
    p_graph: Optional[float] = None
    p_hybrid: float
    structuring_flag: Optional[bool] = None
    ae_available: bool = False
    graph_available: bool = False
    structuring_available: bool = False
    top_contributing_features: list[FeatureHit]
    contributions: list[FeatureHit]
    action_required: bool
    canonical_decision: Optional[str] = None
    canonical_risk_score: Optional[int] = None
    action: Optional[str] = None
    ml_available: Optional[bool] = None
    challenge_id: Optional[str] = None
    challenge_kind: Optional[str] = None
    challenge_note: Optional[str] = None
    model_probability: Optional[float] = None
    reason_codes: list[str] | None = None
    policy_version: Optional[str] = None
    inference_latency_ms: Optional[float] = None


@strawberry.type
class EvaluatePayload:
    transaction_id: str
    user_id: str
    risk_score: int
    decision: str
    action: str
    fraud_probability: float
    location_baseline: str
    processing_time_ms: float
    model_probability: Optional[float] = None
    model_available: Optional[bool] = None
    reason_codes: list[str] | None = None
    policy_version: Optional[str] = None
    inference_latency_ms: Optional[float] = None
    payload: JSON


@strawberry.type
class LoginPayload:
    token: str
    user_id: str


@strawberry.type
class PinPayload:
    ok: bool
    sandbox: bool = True
    note: Optional[str] = None
    error: Optional[str] = None


@strawberry.input
class LocationInput:
    lat: float
    lon: float


@strawberry.input
class ScoreInput:
    transaction_id: str
    amount: float
    payee_vpa: str
    user_id: str
    timestamp: str
    payer_location: Optional[LocationInput] = None
    is_new_payee: bool
    purpose: Optional[str] = None
    device_id: Optional[str] = None


@strawberry.input
class EvaluateInput:
    user_id: str
    amount: float
    currency: str = "INR"
    merchant_id: Optional[str] = None
    merchant_category: Optional[str] = None
    transaction_id: Optional[str] = None
    timestamp: Optional[str] = None
    device_id: Optional[str] = None
    ip_address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    recent_failures: int = 0


def _request(info: Info):
    ctx = info.context
    if isinstance(ctx, dict):
        return ctx["request"]
    return getattr(ctx, "request", ctx)


def _session_user(info: Info) -> str:
    try:
        return require_session(_request(info))
    except HTTPException as exc:
        raise ValueError(exc.detail) from exc


def _enforce_txn_user(info: Info, user_id: str) -> None:
    """Same session policy for scoreTransaction and evaluateTransaction."""
    if not require_login():
        return
    session_user = _session_user(info)
    if session_user != user_id:
        raise ValueError("user mismatch")


def _score_payload(result: dict[str, Any], *, public: bool = False) -> ScorePayload:
    fields = legacy_fields_from_canonical(result)
    hits = [FeatureHit(name=item["name"], value=float(item["value"])) for item in fields["contributions"]]
    return ScorePayload(
        transaction_id=fields["transaction_id"],
        risk_score=fields["risk_score"],
        risk_tier=fields["risk_tier"],
        p_xgb=fields["P_xgb"],
        p_ae=fields["P_ae"],
        p_graph=fields["P_graph"],
        p_hybrid=fields["P_hybrid"],
        structuring_flag=fields["structuring_flag"],
        ae_available=bool(fields.get("ae_available")),
        graph_available=bool(fields.get("graph_available")),
        structuring_available=bool(fields.get("structuring_available")),
        top_contributing_features=hits[:5],
        contributions=hits,
        action_required=fields["action_required"],
        canonical_decision=fields["canonical_decision"],
        canonical_risk_score=fields["canonical_risk_score"],
        action=fields.get("action"),
        ml_available=fields.get("ml_available"),
        challenge_id=None if public else result.get("challenge_id"),
        challenge_kind=None if public else result.get("challenge_kind"),
        challenge_note=None if public else result.get("challenge_note"),
        model_probability=result.get("model_probability"),
        reason_codes=list(result.get("reason_codes") or []),
        policy_version=result.get("policy_version"),
        inference_latency_ms=result.get("inference_latency_ms"),
    )


@strawberry.type
class Query:
    @strawberry.field
    def health(self) -> HealthPayload:
        status = model_status()
        return HealthPayload(
            status="ok",
            model_loaded=status["model_loaded"],
            model_version=status["model_version"],
            ml_fallback=status["ml_fallback"],
        )

    @strawberry.field
    def transactions(self, info: Info, limit: int = 50) -> list[ScorePayload]:
        if require_login():
            _session_user(info)
        rows = get_store().recent_evaluations(min(max(limit, 1), 200))
        out: list[ScorePayload] = []
        for row in rows:
            raw = row.get("result_json")
            if raw:
                try:
                    result = json.loads(raw)
                except json.JSONDecodeError:
                    result = None
            else:
                result = None
            if not isinstance(result, dict):
                result = {
                    "transaction_id": row["transaction_id"],
                    "risk_score": row.get("risk_score") or 0,
                    "decision": row.get("decision") or "REVIEW",
                }
            out.append(_score_payload(result, public=True))
        return out


@strawberry.type
class Mutation:
    @strawberry.mutation
    def login(self, info: Info, user_id: str, password: str) -> LoginPayload:
        store = get_store()
        ident = user_id.strip()
        throttle = login_throttle_key(ident, _request(info))
        try:
            assert_login_not_locked(store, throttle)
        except HTTPException as exc:
            raise ValueError(exc.detail) from exc
        if not store.verify_login(ident, password):
            note_login_failure(store, throttle)
            raise ValueError("invalid credentials")
        token = store.create_session(ident)
        return LoginPayload(token=token, user_id=ident)

    @strawberry.mutation
    def verify_pin(self, info: Info, pin: str, challenge_id: Optional[str] = None) -> PinPayload:
        request = _request(info)
        store = get_store()
        token = bearer_token(request)
        if challenge_id:
            if require_login():
                user_id = _session_user(info)
                token = bearer_token(request)
            else:
                challenge = store.get_challenge(challenge_id.strip())
                if challenge is None:
                    raise ValueError("unknown_challenge")
                session_user = store.session_user(token) if token else None
                user_id = session_user or str(challenge["user_id"])
            outcome = store.verify_challenge(
                challenge_id.strip(),
                user_id=user_id,
                session_token=token,
                pin=pin,
            )
            if not outcome.get("ok"):
                raise ValueError(str(outcome.get("error") or "invalid challenge"))
            return PinPayload(ok=True, sandbox=True, note=outcome.get("note"))
        user_id = _session_user(info)
        if not store.verify_pin(user_id, pin):
            raise ValueError("invalid pin")
        return PinPayload(ok=True, sandbox=True, note="Sandbox PIN, not bank OTP")

    @strawberry.mutation
    def score_transaction(self, info: Info, input: ScoreInput) -> ScorePayload:
        _enforce_txn_user(info, input.user_id)
        raw = {
            "transaction_id": input.transaction_id,
            "amount": input.amount,
            "payee_vpa": input.payee_vpa,
            "user_id": input.user_id,
            "timestamp": input.timestamp,
            "payer_location": (
                {"lat": input.payer_location.lat, "lon": input.payer_location.lon}
                if input.payer_location
                else {}
            ),
            "is_new_payee": input.is_new_payee,
            "purpose": input.purpose,
            "device_id": input.device_id,
        }
        try:
            result = run_pipeline(
                pipeline_payload_from_score(raw),
                client_key=input.user_id,
                session_token=bearer_token(_request(info)),
            )
        except PipelineError as exc:
            raise ValueError(str(exc)) from exc
        logging.getLogger("sentinalpay.api").info(
            "graphql transaction_id=%s account=%s canonical=%s",
            input.transaction_id,
            mask_identifier(input.user_id),
            result.get("decision"),
        )
        return _score_payload(result)

    @strawberry.mutation
    def evaluate_transaction(self, info: Info, input: EvaluateInput) -> EvaluatePayload:
        _enforce_txn_user(info, input.user_id)
        payload = {
            "user_id": input.user_id,
            "amount": input.amount,
            "currency": input.currency,
            "merchant_id": input.merchant_id,
            "merchant_category": input.merchant_category,
            "transaction_id": input.transaction_id,
            "timestamp": input.timestamp,
            "device_id": input.device_id,
            "ip_address": input.ip_address,
            "latitude": input.latitude,
            "longitude": input.longitude,
            "recent_failures": input.recent_failures,
        }
        try:
            result = run_pipeline(payload, client_key=input.user_id, session_token=bearer_token(_request(info)))
        except PipelineError as exc:
            raise ValueError(str(exc)) from exc
        return EvaluatePayload(
            transaction_id=result["transaction_id"],
            user_id=result.get("user_id") or input.user_id,
            risk_score=int(result["risk_score"]),
            decision=str(result["decision"]),
            action=str(result.get("action") or result["decision"]),
            fraud_probability=float(result.get("fraud_probability") or 0.0),
            location_baseline=str(result.get("location_baseline") or "UNKNOWN"),
            processing_time_ms=float(result.get("processing_time_ms") or result.get("processing_ms") or 0.0),
            model_probability=result.get("model_probability"),
            model_available=result.get("model_available"),
            reason_codes=list(result.get("reason_codes") or []),
            policy_version=result.get("policy_version"),
            inference_latency_ms=result.get("inference_latency_ms"),
            payload=result,
        )


schema = strawberry.Schema(query=Query, mutation=Mutation)


async def _context(request: Request, response=None) -> dict[str, Any]:
    return {"request": request}


graphql_router = GraphQLRouter(schema, path="/graphql", context_getter=_context, graphql_ide="graphiql")
