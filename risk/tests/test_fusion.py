"""Fusion policy. Primary R is not an input and BLOCK is never lowered."""

from pathlib import Path

from detection.autoencoder_scorer import AeResult
from risk.config import RiskConfig
from risk.fusion import fuse_decision
from risk.pipeline import evaluate_transaction
from risk.secondary import assess_secondary
from risk.store import RiskStore
from risk.tests.test_secondary import _evidence


def _exp(**overrides):
    body = {
        "ae_available": True,
        "P_ae": 0.2,
        "graph_available": True,
        "P_graph": 0.02,
        "structuring_flag": False,
        "mule_cluster": False,
    }
    body.update(overrides)
    return body


def test_low_primary_and_normal_signals_stay_allow() -> None:
    fused = fuse_decision("ALLOW", _exp())
    assert fused["decision"] == "ALLOW"
    assert fused["reasons"] == ["within_bands"]


def test_strong_autoencoder_escalates_allow_but_not_to_block() -> None:
    fused = fuse_decision("ALLOW", _exp(P_ae=1.0))
    assert fused["decision"] == "REVIEW"
    assert fused["reasons"] == ["ae_anomaly"]


def test_routine_amount_keeps_allow_when_graph_and_autoencoder_fire() -> None:
    flags = _exp(P_ae=1.0, structuring_flag=True, mule_cluster=True, P_graph=0.825)
    small = fuse_decision("ALLOW", flags, amount=500)
    assert small["decision"] == "ALLOW"
    assert small["reasons"][0] == "routine_amount_kept"
    larger = fuse_decision("ALLOW", flags, amount=501)
    assert larger["decision"] == "REVIEW"


def test_graph_flags_escalate_allow_fanout_does_not() -> None:
    flagged = fuse_decision("ALLOW", _exp(structuring_flag=True, P_graph=0.4))
    assert flagged["decision"] == "REVIEW"
    assert flagged["reasons"] == ["graph_network"]
    fanout = fuse_decision("ALLOW", _exp(P_graph=1.0, structuring_flag=False, mule_cluster=False))
    assert fanout["decision"] == "ALLOW"
    assert fanout["graph_state"] == "normal"


def test_corroborated_review_is_not_blocked_without_a_validated_cut() -> None:
    fused = fuse_decision("REVIEW", _exp(P_ae=1.0, mule_cluster=True, P_graph=0.35))
    assert fused["decision"] == "REVIEW"
    assert fused["reasons"] == ["ae_and_graph_unvalidated_for_block"]


def test_unavailable_models_do_not_manufacture_or_cancel_allow() -> None:
    missing = fuse_decision("ALLOW", {"ae_available": False, "P_ae": None, "graph_available": False, "P_graph": None})
    assert missing["decision"] == "ALLOW"
    assert missing["reasons"] == ["models_unavailable_primary_kept"]
    review = fuse_decision("REVIEW", {"ae_available": False, "graph_available": False})
    assert review["decision"] == "REVIEW"


def test_block_survives_normal_signals() -> None:
    fused = fuse_decision("BLOCK", _exp(P_ae=0.0, P_graph=0.0))
    assert fused["decision"] == "BLOCK"
    assert fused["reasons"] == ["primary_block_kept"]


def test_secondary_graph_flag_rejects_and_ae_flag_steps_up() -> None:
    rejected = assess_secondary(_evidence(graph_state="strong", ae_state="normal"))
    assert rejected["outcome"] == "REJECT"
    assert "graph_network" in rejected["reasons"]
    stepped = assess_secondary(_evidence(ae_state="strong", graph_state="normal"))
    assert stepped["outcome"] == "STEP_UP"
    assert stepped["reasons"] == ["ae_anomaly"]
    held = assess_secondary(_evidence(history=[], ae_state="strong", graph_state="normal"))
    assert held["outcome"] == "CONTINUE_HOLD"
    assert "ae_anomaly" in held["reasons"]


def test_pipeline_failure_and_missing_artifact_do_not_fake_a_score(tmp_path: Path, monkeypatch) -> None:
    def down(_vector):
        return AeResult(available=False, score=None, error="inference_error", n_features=10)

    monkeypatch.setattr("risk.pipeline.infer_autoencoder", down)

    def boom(*_args, **_kwargs):
        raise RuntimeError("graph down")

    monkeypatch.setattr("risk.pipeline.score_graph", boom)
    result = evaluate_transaction(
        {
            "transaction_id": "fuse-down",
            "user_id": "USR_FUSE_DOWN",
            "amount": 200.0,
            "merchant_id": "kirana@oksbi",
            "timestamp": "2026-09-28T12:00:00+00:00",
            "device_id": "dev-fuse",
            "latitude": 12.97,
            "longitude": 77.59,
        },
        store=RiskStore(tmp_path / "down.db"),
        config=RiskConfig(),
    )
    assert result["experimental"]["P_ae"] is None
    assert result["experimental"]["ae_available"] is False
    assert result["experimental"]["P_graph"] is None
    assert result["experimental"]["graph_available"] is False
    assert result["fusion"]["ae_state"] == "unavailable"
    assert result["fusion"]["graph_state"] == "unavailable"
    assert set(result["components"]) == {"rules", "behavior", "ml", "security"}
    if result["fusion"]["primary_decision"] == "ALLOW":
        assert result["decision"] == "ALLOW"
