"""Incremental directed payment graph for structuring and mule-chain signals.

`score_graph` is read-only. `add_transaction` is the only mutator. Caller
objects are never modified.

Live scoring builds a bounded window from `RiskStore.windowed_transactions`
(default 24h, capped at 2000 rows). That graph is discarded after the
request — it is not durable history. Duplicate `transaction_id`s are ignored.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from math import isfinite
from typing import Any, Mapping, Sequence

import networkx as nx

from detection.privacy import mask_identifier

WINDOW_SECONDS: float = float(os.getenv("SENTINALPAY_GRAPH_WINDOW_SECONDS", str(24 * 60 * 60)))
STRUCTURING_AMOUNT: float = float(os.getenv("SENTINALPAY_STRUCTURING_AMOUNT", "50000"))
MULE_CLUSTER_MIN: int = int(os.getenv("SENTINALPAY_MULE_CLUSTER_MIN", "5"))


class GraphValidationError(ValueError):
    """Raised when a transaction cannot be added to the graph."""


def empty_graph() -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    graph.graph["txn_ids"] = set()
    return graph


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
    """Add one directed edge. Duplicate transaction_id is ignored. Does not mutate `txn`."""
    if not isinstance(txn, Mapping):
        raise GraphValidationError("transaction must be a mapping")
    sender = _require_account(txn.get("user_id") or txn.get("sender") or txn.get("payer_vpa"), "user_id")
    receiver = _require_account(txn.get("payee_vpa") or txn.get("receiver") or txn.get("merchant_id"), "payee_vpa")
    amount = _require_amount(txn.get("amount"))
    timestamp = _require_timestamp(txn.get("timestamp"))
    txn_id = str(txn.get("transaction_id") or "").strip() or f"{sender}->{receiver}@{timestamp.isoformat()}"
    seen: set[str] = graph.graph.setdefault("txn_ids", set())
    if txn_id in seen:
        return
    seen.add(txn_id)
    graph.add_edge(
        sender,
        receiver,
        amount=amount,
        timestamp=timestamp,
        transaction_id=txn_id,
    )


def graph_from_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    as_of: datetime,
    window_s: float | None = None,
    skip_ids: set[str] | None = None,
) -> nx.MultiDiGraph:
    """Bounded window graph from persisted rows. Candidate id should be in skip_ids."""
    as_of = _require_timestamp(as_of)
    window = WINDOW_SECONDS if window_s is None else float(window_s)
    start = as_of - timedelta(seconds=window)
    skip = skip_ids or set()
    graph = empty_graph()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        tid = str(row.get("transaction_id") or "").strip()
        if tid and tid in skip:
            continue
        ts_raw = row.get("timestamp")
        try:
            ts = _require_timestamp(ts_raw)
        except GraphValidationError:
            continue
        if ts < start or ts > as_of:
            continue
        try:
            add_transaction(graph, row)
        except GraphValidationError:
            continue
    return graph


def _window_subgraph(graph: nx.MultiDiGraph, end: datetime) -> nx.MultiDiGraph:
    start = end - timedelta(seconds=WINDOW_SECONDS)
    sub = empty_graph()
    for src, dest, data in graph.edges(data=True):
        ts = data.get("timestamp")
        if isinstance(ts, datetime) and start <= ts <= end:
            sub.add_edge(src, dest, **data)
    return sub


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
    """Latest edge time in the graph. Window end is graph-now, not the account's last hop."""
    stamps: list[datetime] = []
    for _, _, data in graph.edges(data=True):
        ts = data.get("timestamp")
        if isinstance(ts, datetime):
            stamps.append(ts)
    return max(stamps) if stamps else datetime.now(timezone.utc)


def graph_signals(graph: nx.MultiDiGraph, account_id: str, as_of: datetime | None = None) -> dict[str, Any]:
    """Rolling-window features for one account. Read-only."""
    account_id = _require_account(account_id, "account_id")
    end = _require_timestamp(as_of) if as_of is not None else _as_of(graph, account_id)
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
    windowed = _window_subgraph(graph, end)
    cluster_size = 1 if account_id in windowed else 0
    if account_id in windowed and windowed.number_of_nodes() > 0:
        for component in nx.weakly_connected_components(windowed):
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


def score_graph(graph: nx.MultiDiGraph, account_id: str, as_of: datetime | None = None) -> float:
    """Combine graph signals into a 0–1 heuristic. Does not mutate `graph`.

    Demo weights, not a calibrated detector: structuring 0.40, mule 0.35,
    fan-out 0.15, fan-in 0.10. Not blended into ALLOW/REVIEW/BLOCK.
    """
    signals = graph_signals(graph, account_id, as_of=as_of)
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
    "graph_from_rows",
    "graph_signals",
    "score_graph",
]
