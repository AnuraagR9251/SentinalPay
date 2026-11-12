"""Fuse autoencoder and graph evidence after the primary score.

The primary blend is unchanged:

    R = 0.25*S_rules + 0.25*S_behavior + 0.40*(100*P_xgb) + 0.10*S_security

This layer never writes into R and never downgrades BLOCK.

Autoencoder. `P_ae` is reconstruction MSE divided by the saved threshold, clipped
to [0, 1]. That threshold is the 95th percentile of legitimate reconstruction
error in `ml/train_autoencoder.py`, stored in `ml/models/autoencoder_threshold.json`.
The trainer fit that percentile on the chronological 20% holdout, which is the
same cut the XGBoost trainer uses as its test split. It is not a fresh
validation operating point. Strong means `P_ae >= 1` (error at or above that
saved percentile). Below 1 stays inside that band. A missing model is
unavailable, not 0.

Graph. `score_graph` is a deterministic heuristic, not a trained model:

    0.40*structuring + 0.35*mule + 0.15*min(1, fan_out/8) + 0.10*min(1, fan_in/8)

Fan-in and fan-out overlap the existing velocity and new-payee rules, so they
do not escalate on their own. Structuring (three or more sub-₹50,000 sends in
the 24h window whose sum exceeds ₹50,000) and a weakly connected component of
at least 5 accounts are the only graph flags that escalate. Those cuts are the
heuristic's own constants in `detection/graph_features.py`, not a label-tuned
threshold.

Joint BLOCK is not used. No validation split was held out from the saved
autoencoder threshold, and the graph score has no fraud labels, so corroborated
anomaly evidence escalates a larger ALLOW to REVIEW and leaves an existing
REVIEW in place. `policy_action` then maps that REVIEW to STEP_UP or HOLD.

A send at or under ₹500 keeps a primary ALLOW. The structuring cut is a 24h
total and the mule cut is a 5-account component, so either one will trip during
ordinary demo use. They must not hold a routine payment whose own score is ALLOW.
"""

from __future__ import annotations

from typing import Any, Mapping

from risk.policy import ROUTINE_ALLOW_MAX_AMOUNT

# error >= saved p95 legitimate reconstruction error
AE_STRONG_SCORE = 1.0


def _ae_state(experimental: Mapping[str, Any]) -> str:
    if experimental.get("ae_available") is not True:
        return "unavailable"
    score = experimental.get("P_ae")
    try:
        value = float(score)
    except (TypeError, ValueError):
        return "unavailable"
    if value != value or value < 0:
        return "unavailable"
    if value >= AE_STRONG_SCORE:
        return "strong"
    return "normal"


def _graph_state(experimental: Mapping[str, Any]) -> str:
    if experimental.get("graph_available") is not True:
        return "unavailable"
    if experimental.get("structuring_flag") is True or experimental.get("mule_cluster") is True:
        return "strong"
    return "normal"


def _routine_amount(amount: float | None) -> bool:
    if amount is None:
        return False
    try:
        return float(amount) <= ROUTINE_ALLOW_MAX_AMOUNT
    except (TypeError, ValueError):
        return False


def fuse_decision(
    primary_decision: str,
    experimental: Mapping[str, Any] | None,
    amount: float | None = None,
) -> dict[str, Any]:
    """Return the decision the rest of the policy must enforce. R is not an input."""
    primary = primary_decision if primary_decision in {"ALLOW", "REVIEW", "BLOCK"} else "REVIEW"
    exp = experimental or {}
    ae_state = _ae_state(exp)
    graph_state = _graph_state(exp)
    if primary == "BLOCK":
        reasons = ["primary_block_kept"]
        decision = "BLOCK"
    elif ae_state == "strong" and graph_state == "strong":
        reasons = ["ae_and_graph_unvalidated_for_block"]
        decision = "REVIEW" if primary == "ALLOW" else primary
    elif ae_state == "strong":
        reasons = ["ae_anomaly"]
        decision = "REVIEW" if primary == "ALLOW" else primary
    elif graph_state == "strong":
        reasons = ["graph_network"]
        decision = "REVIEW" if primary == "ALLOW" else primary
    elif primary == "ALLOW":
        reasons = ["within_bands" if ae_state == "normal" or graph_state == "normal" else "models_unavailable_primary_kept"]
        decision = "ALLOW"
    else:
        reasons = ["primary_review_kept"]
        decision = primary
    if primary == "ALLOW" and decision != "ALLOW" and _routine_amount(amount):
        reasons = ["routine_amount_kept", *reasons]
        decision = "ALLOW"
    return {
        "primary_decision": primary,
        "decision": decision,
        "reasons": reasons,
        "ae_state": ae_state,
        "graph_state": graph_state,
    }
