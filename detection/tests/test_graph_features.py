"""Graph features: clean account, structuring, and mule-chain cases."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from detection.graph_features import (
    GraphValidationError,
    add_transaction,
    empty_graph,
    graph_signals,
    score_graph,
)

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)


def _txn(
    *,
    sender: str,
    payee: str,
    amount: float,
    minutes: int = 0,
    txn_id: str = "t",
) -> dict[str, object]:
    return {
        "transaction_id": txn_id,
        "user_id": sender,
        "payee_vpa": payee,
        "amount": amount,
        "timestamp": NOW + timedelta(minutes=minutes),
    }


def test_normal_account_low_score() -> None:
    graph = empty_graph()
    add_transaction(graph, _txn(sender="aarav@oksbi", payee="kirana@oksbi", amount=220.0, txn_id="n1"))
    add_transaction(graph, _txn(sender="aarav@oksbi", payee="kirana@oksbi", amount=180.0, minutes=40, txn_id="n2"))
    signals = graph_signals(graph, "aarav@oksbi")
    assert signals["structuring_flag"] is False
    assert signals["mule_cluster"] is False
    assert score_graph(graph, "aarav@oksbi") < 0.25


def test_structuring_pattern_flags() -> None:
    graph = empty_graph()
    sender = "smurf@oksbi"
    for i, amount in enumerate((18000.0, 19000.0, 17000.0)):
        add_transaction(
            graph,
            _txn(sender=sender, payee="mule.cash@okaxis", amount=amount, minutes=i * 5, txn_id=f"s{i}"),
        )
    signals = graph_signals(graph, sender)
    assert signals["structuring_flag"] is True
    assert score_graph(graph, sender) >= 0.40


def test_mule_chain_high_cluster_risk() -> None:
    graph = empty_graph()
    chain = [f"acct{i}@oksbi" for i in range(6)]
    for i in range(len(chain) - 1):
        add_transaction(
            graph,
            _txn(sender=chain[i], payee=chain[i + 1], amount=8000.0, minutes=i * 3, txn_id=f"m{i}"),
        )
    signals = graph_signals(graph, chain[0])
    assert signals["cluster_size"] >= 6
    assert signals["mule_cluster"] is True
    assert score_graph(graph, chain[0]) >= 0.35


def test_rejects_bad_amount() -> None:
    graph = empty_graph()
    with pytest.raises(GraphValidationError):
        add_transaction(graph, _txn(sender="a@oksbi", payee="b@oksbi", amount=-1.0))
