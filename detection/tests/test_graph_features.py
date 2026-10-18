"""Graph features: clean account, structuring, and mule-chain cases."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from detection.graph_features import (
    GraphValidationError,
    WINDOW_SECONDS,
    add_transaction,
    empty_graph,
    graph_from_rows,
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


def test_fan_out_raises_score() -> None:
    graph = empty_graph()
    sender = "busy@oksbi"
    for i in range(8):
        add_transaction(
            graph,
            _txn(sender=sender, payee=f"payee{i}@oksbi", amount=200.0, minutes=i, txn_id=f"fo{i}"),
        )
    signals = graph_signals(graph, sender, as_of=NOW + timedelta(hours=1))
    assert signals["fan_out_count"] == 8
    assert score_graph(graph, sender, as_of=NOW + timedelta(hours=1)) >= 0.15


def test_fan_in_raises_score() -> None:
    graph = empty_graph()
    payee = "hub@oksbi"
    for i in range(8):
        add_transaction(
            graph,
            _txn(sender=f"src{i}@oksbi", payee=payee, amount=200.0, minutes=i, txn_id=f"fi{i}"),
        )
    signals = graph_signals(graph, payee, as_of=NOW + timedelta(hours=1))
    assert signals["fan_in_count"] == 8
    assert score_graph(graph, payee, as_of=NOW + timedelta(hours=1)) >= 0.10


def test_old_edges_excluded_from_mule_cluster() -> None:
    graph = empty_graph()
    chain = [f"old{i}@oksbi" for i in range(6)]
    stale = NOW - timedelta(seconds=WINDOW_SECONDS + 3600)
    for i in range(len(chain) - 1):
        add_transaction(
            graph,
            {
                "transaction_id": f"old{i}",
                "user_id": chain[i],
                "payee_vpa": chain[i + 1],
                "amount": 8000.0,
                "timestamp": stale,
            },
        )
    signals = graph_signals(graph, chain[0], as_of=NOW)
    assert signals["mule_cluster"] is False
    assert signals["cluster_size"] in {0, 1}


def test_duplicate_transaction_id_ignored() -> None:
    graph = empty_graph()
    first = _txn(sender="a@oksbi", payee="b@oksbi", amount=100.0, txn_id="dup-1")
    add_transaction(graph, first)
    add_transaction(graph, _txn(sender="a@oksbi", payee="c@oksbi", amount=999.0, minutes=1, txn_id="dup-1"))
    assert graph.number_of_edges() == 1
    signals = graph_signals(graph, "a@oksbi", as_of=NOW + timedelta(hours=1))
    assert signals["fan_out_count"] == 1


def test_missing_history_score_is_zero() -> None:
    graph = empty_graph()
    assert score_graph(graph, "ghost@oksbi", as_of=NOW) == 0.0
    signals = graph_signals(graph, "ghost@oksbi", as_of=NOW)
    assert signals["structuring_flag"] is False
    assert signals["mule_cluster"] is False


def test_graph_from_rows_skips_candidate_and_future() -> None:
    rows = [
        _txn(sender="a@oksbi", payee="b@oksbi", amount=100.0, minutes=-10, txn_id="keep"),
        _txn(sender="a@oksbi", payee="c@oksbi", amount=100.0, minutes=0, txn_id="candidate"),
        _txn(sender="a@oksbi", payee="d@oksbi", amount=100.0, minutes=30, txn_id="future"),
    ]
    graph = graph_from_rows(rows, as_of=NOW, skip_ids={"candidate"})
    add_transaction(graph, rows[1])
    signals = graph_signals(graph, "a@oksbi", as_of=NOW)
    assert signals["fan_out_count"] == 2
    assert graph.number_of_edges() == 2
