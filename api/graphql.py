"""GraphQL adapter. Same pipeline as REST — no second scoring engine."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import strawberry
from fastapi import HTTPException, Request
from graphql import GraphQLError
from strawberry.fastapi import GraphQLRouter
from strawberry.scalars import JSON
from strawberry.types import Info

from api.compat import legacy_fields_from_canonical, pipeline_payload_from_score
from detection.privacy import mask_identifier
from risk.auth import (
    assert_login_not_locked,
    bearer_token,
    login_throttle_key,
    logout_request,
    note_login_failure,
    open_access_warning,
    protect_sensitive,
    require_login,
    require_session,
    verify_pin_request,
)
from risk.ml_layer import model_status
from risk.pipeline import PipelineError, http_status_for_pipeline_error
from risk.pipeline import evaluate_transaction as run_pipeline
from risk.store import get_store

_LOG = logging.getLogger("sentinalpay.api")
_SAFE_SCORE_ERROR = "scoring unavailable"


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
    ae_loaded: bool = False
    ae_error: Optional[str] = None
    open_sandbox: bool = False
    auth_warning: Optional[str] = None
    ml_calibrated_for_upi: bool = False
    ml_evaluation: Optional[str] = None
    ml_experimental: bool = False
    ml_note: Optional[str] = None


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
    ml_calibrated_for_upi: Optional[bool] = None
    ml_evaluation: Optional[str] = None
    score_components: Optional[JSON] = None


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


def _raise_status(status: int, message: str) -> None:
    raise GraphQLError(
        message,
        extensions={"code": int(status), "httpStatus": int(status)},
    ) from None


def _raise_http(exc: HTTPException) -> None:
    _raise_status(int(exc.status_code), str(exc.detail))


def _raise_pipeline(exc: PipelineError) -> None:
    _raise_status(http_status_for_pipeline_error(exc), str(exc))


def _run_scored_pipeline(info: Info, payload: dict[str, Any], client_key: str) -> dict[str, Any]:
    try:
        return run_pipeline(
            payload,
            client_key=client_key,
            session_token=bearer_token(_request(info)),
        )
    except PipelineError as exc:
        _raise_pipeline(exc)
        raise
    except Exception:
        _LOG.exception("graphql scoring failed")
        _raise_status(500, _SAFE_SCORE_ERROR)
        raise


def _session_user(info: Info) -> str:
    try:
        return require_session(_request(info))
    except HTTPException as exc:
        _raise_http(exc)
        raise


def _protect(info: Info) -> str:
    try:
        return protect_sensitive(_request(info))
    except HTTPException as exc:
        _raise_http(exc)
        raise


def _enforce_txn_user(info: Info, user_id: str) -> str:
    """API key + HTTP limit, then the same session policy as REST."""
    client_key = _protect(info)
    if not require_login():
        return client_key
    session_user = _session_user(info)
    if session_user != user_id:
        raise GraphQLError("user mismatch", extensions={"code": 403, "httpStatus": 403})
    return client_key


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
        ml_calibrated_for_upi=fields.get("ml_calibrated_for_upi"),
        ml_evaluation=fields.get("ml_evaluation"),
        score_components=fields.get("score_components"),
    )


@strawberry.type
class Query:
    @strawberry.field
    def health(self) -> HealthPayload:
        status = model_status()
        try:
            from detection.autoencoder_scorer import ae_status

            ae = ae_status()
        except Exception:
            ae = {"ae_loaded": False, "ae_error": "status_error"}
        return HealthPayload(
            status="ok",
            model_loaded=status["model_loaded"],
            model_version=status["model_version"],
            ml_fallback=status["ml_fallback"],
            ae_loaded=bool(ae.get("ae_loaded")),
            ae_error=ae.get("ae_error"),
            open_sandbox=not require_login(),
            auth_warning=open_access_warning(),
            ml_calibrated_for_upi=bool(status.get("calibrated_for_upi")),
            ml_evaluation=status.get("evaluation"),
            ml_experimental=bool(status.get("experimental")),
            ml_note=status.get("note"),
        )

    @strawberry.field
    def transactions(self, info: Info, limit: int = 50) -> list[ScorePayload]:
        _protect(info)
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
            _raise_http(exc)
        if not store.verify_login(ident, password):
            note_login_failure(store, throttle)
            raise ValueError("invalid credentials")
        token = store.create_session(ident)
        return LoginPayload(token=token, user_id=ident)

    @strawberry.mutation
    def logout(self, info: Info) -> bool:
        try:
            logout_request(_request(info))
        except HTTPException as exc:
            _raise_http(exc)
        return True

    @strawberry.mutation
    def verify_pin(self, info: Info, pin: str, challenge_id: Optional[str] = None) -> PinPayload:
        try:
            outcome = verify_pin_request(_request(info), pin, challenge_id)
        except HTTPException as exc:
            detail = str(exc.detail or "")
            code = detail.strip().lower().replace(" ", "_")
            if exc.status_code in {401, 429} and (
                code in {"invalid_pin", "locked", "unknown_challenge", "expired", "replay", "session_mismatch"}
                or "too_many_pin" in code
            ):
                if "too_many_pin" in code:
                    code = "locked"
                return PinPayload(ok=False, sandbox=True, error=code)
            _raise_http(exc)
        return PinPayload(ok=True, sandbox=True, note=outcome.get("note"), error=None)

    @strawberry.mutation
    def score_transaction(self, info: Info, input: ScoreInput) -> ScorePayload:
        client_key = _enforce_txn_user(info, input.user_id)
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
        result = _run_scored_pipeline(info, pipeline_payload_from_score(raw), client_key)
        _LOG.info(
            "graphql transaction_id=%s account=%s canonical=%s",
            input.transaction_id,
            mask_identifier(input.user_id),
            result.get("decision"),
        )
        return _score_payload(result)

    @strawberry.mutation
    def evaluate_transaction(self, info: Info, input: EvaluateInput) -> EvaluatePayload:
        client_key = _enforce_txn_user(info, input.user_id)
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
        result = _run_scored_pipeline(info, payload, client_key)
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


class SentinalSchema(strawberry.Schema):
    def process_errors(self, errors, execution_context=None) -> None:
        noisy = []
        for error in errors:
            status = (error.extensions or {}).get("httpStatus")
            if status in (401, 403, 409, 422, 429, 500):
                continue
            noisy.append(error)
        if noisy:
            super().process_errors(noisy, execution_context)


schema = SentinalSchema(query=Query, mutation=Mutation)


async def _context(request: Request, response=None) -> dict[str, Any]:
    return {"request": request}


graphql_router = GraphQLRouter(schema, path="/graphql", context_getter=_context, graphql_ide="graphiql")
