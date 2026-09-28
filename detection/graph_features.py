"""Incremental directed payment graph for structuring and mule-chain signals.

`score_graph` is read-only. `add_transaction` is the only mutator. Caller
objects are never modified.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any, Mapping

import networkx as nx

from detection.privacy import mask_identifier

WINDOW_SECONDS: float = float(os.getenv("SENTINALPAY_GRAPH_WINDOW_SECONDS", str(24 * 60 * 60)))
STRUCTURING_AMOUNT: float = float(os.getenv("SENTINALPAY_STRUCTURING_AMOUNT", "50000"))
MULE_CLUSTER_MIN: int = int(os.getenv("SENTINALPAY_MULE_CLUSTER_MIN", "5"))


class GraphValidationError(ValueError):
    """Raised when a transaction cannot be added to the graph."""


def empty_graph() -> nx.MultiDiGraph:
    return nx.MultiDiGraph()


def _require_account(value: Any, field_name: str) -> str:
    if value is None or not isinstance(value, str) or not value.strip():
        raise GraphValidationError(f"{field_name} is required and must be a non-empty string")
    return value.strip()


def _require_amount(value: Any) -> float:
    if isinstance(value, bool) or value is None:
        raise GraphValidationError("amount must be a positive finite number")
    try:
        amount = float(value)
    except (TypeError, ValueError) as exc:
        raise GraphValidationError("amount must be a positive finite number") from exc
    if not isfinite(amount) or amount <= 0:
        raise GraphValidationError("amount must be a positive finite number")
    return amount


def _require_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        ts = value
    elif isinstance(value, str) and value.strip():
        try:
            ts = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise GraphValidationError("timestamp must be ISO-8601 or a datetime") from exc
    else:
        raise GraphValidationError("timestamp must be ISO-8601 or a datetime")
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def add_transaction(graph: nx.MultiDiGraph, txn: Mapping[str, Any]) -> None:
    """Add one directed edge. Does not mutate `txn`."""
    if not isinstance(txn, Mapping):
        raise GraphValidationError("transaction must be a mapping")
    sender = _require_account(txn.get("user_id") or txn.get("sender") or txn.get("payer_vpa"), "user_id")
    receiver = _require_account(txn.get("payee_vpa") or txn.get("receiver"), "payee_vpa")
    amount = _require_amount(txn.get("amount"))
    timestamp = _require_timestamp(txn.get("timestamp"))
    txn_id = str(txn.get("transaction_id") or "").strip() or f"{sender}->{receiver}"
    graph.add_edge(
        sender,
        receiver,
        amount=amount,
        timestamp=timestamp,
        transaction_id=txn_id,
    )


def _window_out_edges(graph: nx.MultiDiGraph, account_id: str, end: datetime) -> list[tuple[str, str, dict[str, Any]]]:
    start = end - timedelta(seconds=WINDOW_SECONDS)
    rows: list[tuple[str, str, dict[str, Any]]] = []
    if account_id not in graph:
        return rows
    for _, dest, data in graph.out_edges(account_id, data=True):
        ts = data.get("timestamp")
        if isinstance(ts, datetime) and start <= ts <= end:
            rows.append((account_id, dest, data))
    return rows


def _window_in_edges(graph: nx.MultiDiGraph, account_id: str, end: datetime) -> list[tuple[str, str, dict[str, Any]]]:
    start = end - timedelta(seconds=WINDOW_SECONDS)
    rows: list[tuple[str, str, dict[str, Any]]] = []
    if account_id not in graph:
        return rows
    for src, _, data in graph.in_edges(account_id, data=True):
        ts = data.get("timestamp")
        if isinstance(ts, datetime) and start <= ts <= end:
            rows.append((src, account_id, data))
    return rows


def _as_of(graph: nx.MultiDiGraph, account_id: str) -> datetime:
    stamps: list[datetime] = []
    if account_id in graph:
        for _, _, data in graph.out_edges(account_id, data=True):
            ts = data.get("timestamp")
            if isinstance(ts, datetime):
                stamps.append(ts)
        for _, _, data in graph.in_edges(account_id, data=True):
            ts = data.get("timestamp")
            if isinstance(ts, datetime):
                stamps.append(ts)
    return max(stamps) if stamps else datetime.now(timezone.utc)


def graph_signals(graph: nx.MultiDiGraph, account_id: str) -> dict[str, Any]:
    """Rolling-window features for one account. Read-only."""
    account_id = _require_account(account_id, "account_id")
    end = _as_of(graph, account_id)
    outgoing = _window_out_edges(graph, account_id, end)
    incoming = _window_in_edges(graph, account_id, end)

    fan_out_count = len({dest for _, dest, _ in outgoing})
    fan_in_count = len({src for src, _, _ in incoming})
    total_sent_rolling = sum(float(data.get("amount") or 0.0) for _, _, data in outgoing)

    known_payees: set[str] = set()
    if account_id in graph:
        for _, dest, data in graph.out_edges(account_id, data=True):
            ts = data.get("timestamp")
            if isinstance(ts, datetime) and ts < end - timedelta(seconds=WINDOW_SECONDS):
                known_payees.add(dest)
    new_txn_count = 0
    for _, dest, _ in sorted(outgoing, key=lambda item: item[2].get("timestamp") or end):
        if dest not in known_payees:
            new_txn_count += 1
        known_payees.add(dest)
    new_payee_ratio = (new_txn_count / len(outgoing)) if outgoing else 0.0

    small = [float(data.get("amount") or 0.0) for _, _, data in outgoing if float(data.get("amount") or 0.0) < STRUCTURING_AMOUNT]
    structuring_flag = len(small) >= 3 and sum(small) > STRUCTURING_AMOUNT

    mule_cluster = False
    cluster_size = 1 if account_id in graph else 0
    if account_id in graph and graph.number_of_nodes() > 0:
        for component in nx.weakly_connected_components(graph):
            if account_id in component:
                cluster_size = len(component)
                mule_cluster = cluster_size >= MULE_CLUSTER_MIN
                break

    return {
        "account_id_masked": mask_identifier(account_id),
        "fan_out_count": fan_out_count,
        "fan_in_count": fan_in_count,
        "total_sent_rolling": total_sent_rolling,
        "new_payee_ratio": new_payee_ratio,
        "structuring_flag": structuring_flag,
        "mule_cluster": mule_cluster,
        "cluster_size": cluster_size,
    }


def score_graph(graph: nx.MultiDiGraph, account_id: str) -> float:
    """Combine graph signals into a 0–1 risk score. Does not mutate `graph` inputs.

    Weighting: structuring 0.40 and mule-cluster 0.35 — those are the
    strongest cash-out / smurfing cues. Fan-out 0.15 and fan-in 0.10 are
    supporting (a busy merchant can have high degree without fraud).
    """
    signals = graph_signals(graph, account_id)
    fan_out = min(1.0, float(signals["fan_out_count"]) / 8.0)
    fan_in = min(1.0, float(signals["fan_in_count"]) / 8.0)
    structuring = 1.0 if signals["structuring_flag"] else 0.0
    mule = 1.0 if signals["mule_cluster"] else 0.0
    return min(1.0, 0.40 * structuring + 0.35 * mule + 0.15 * fan_out + 0.10 * fan_in)


__all__ = [
    "GraphValidationError",
    "MULE_CLUSTER_MIN",
    "STRUCTURING_AMOUNT",
    "WINDOW_SECONDS",
    "add_transaction",
    "empty_graph",
    "graph_signals",
    "score_graph",
]
