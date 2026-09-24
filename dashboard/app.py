"""SentinalPay analyst dashboard — Phase 1 Streamlit UI.

Talks only to a `TransactionSource`. The default source is the in-process
simulator; replace `SimulatedStream` with `HttpTransactionSource` when a
FastAPI endpoint exists.

# TODO: apply rate limiting here before production use
# TODO: persist via parameterized queries / ORM only — never string-formatted SQL
"""

from __future__ import annotations

import math
import sys
import time
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from data_simulator import SimulatedStream  # type: ignore  # noqa: E402
except ImportError:
    from dashboard.data_simulator import SimulatedStream  # noqa: E402
from detection.models import (  # noqa: E402
    FeatureContribution,
    PaymentRiskLabel,
    RiskAssessment,
    RiskTier,
    Transaction,
)

# One semantic palette — used for KPIs, badges, probability bars, and feature bars.
COLOR_LEGIT = "#1B7F4E"
COLOR_STEP = "#C47B17"
COLOR_HOLD = "#B45309"
COLOR_BLOCK = "#C0392B"
COLOR_IDLE = "#3a4a5c"
COLOR_QUEUED = "#3ee0c5"

TIER_LABELS = {
    RiskTier.ALLOW: "Legit",
    RiskTier.STEP_UP: "Step-up",
    RiskTier.HOLD: "Hold",
    RiskTier.BLOCK: "Block",
}
TIER_ACTIONS = {
    RiskTier.ALLOW: "log only",
    RiskTier.STEP_UP: "OTP / re-confirmation",
    RiskTier.HOLD: "delayed settlement",
    RiskTier.BLOCK: "account lock",
}
RISK_LABELS = {
    PaymentRiskLabel.LEGIT: "Legit",
    PaymentRiskLabel.SUSPICIOUS: "Suspicious",
    PaymentRiskLabel.LIKELY_FRAUD: "Risk",
}
RISK_COLORS = {
    "Legit": COLOR_LEGIT,
    "Suspicious": COLOR_STEP,
    "Risk": COLOR_BLOCK,
    "—": COLOR_IDLE,
}
_CITY_CENTRES: tuple[tuple[str, float, float], ...] = (
    ("Pune", 18.5204, 73.8567),
    ("Mumbai", 19.0760, 72.8777),
    ("Delhi", 28.6139, 77.2090),
    ("Bengaluru", 12.9716, 77.5946),
    ("Hyderabad", 17.3850, 78.4867),
    ("Chennai", 13.0827, 80.2707),
    ("Kolkata", 22.5726, 88.3639),
)
REFRESH_SECONDS = 1.6

st.set_page_config(
    page_title="SentinalPay · Fraud Desk",
    page_icon="SP",
    layout="wide",
    initial_sidebar_state="collapsed",
)

_THEME = Path(__file__).with_name("theme.css").read_text(encoding="utf-8")
st.markdown(f"<style>{_THEME}</style>", unsafe_allow_html=True)


def _enum_value(item) -> str:
    return str(getattr(item, "value", item))


def _tier_label(tier) -> str:
    return {t.value: name for t, name in TIER_LABELS.items()}.get(_enum_value(tier), "—")


def _tier_action(tier) -> str:
    return {t.value: name for t, name in TIER_ACTIONS.items()}.get(_enum_value(tier), "")


def _risk_label(label) -> str:
    if label is None:
        return "—"
    return {t.value: name for t, name in RISK_LABELS.items()}.get(_enum_value(label), "—")


def _nearest_city(lat: float | None, lon: float | None) -> str:
    if lat is None or lon is None:
        return "—"
    best_name = "Unknown"
    best_dist = float("inf")
    for name, clat, clon in _CITY_CENTRES:
        dist = math.hypot(lat - clat, lon - clon)
        if dist < best_dist:
            best_dist = dist
            best_name = name
    return f"{best_name} ({lat:.2f}, {lon:.2f})"


def _init_state() -> None:
    if "source" not in st.session_state:
        stream = SimulatedStream()
        stream.prime(18)
        st.session_state.source = stream
    if "paused" not in st.session_state:
        st.session_state.paused = False
    if "selected_txn_id" not in st.session_state:
        st.session_state.selected_txn_id = None


def _rows(pairs: list[tuple[Transaction, RiskAssessment]]) -> pd.DataFrame:
    records = []
    for txn, assessment in pairs:
        records.append(
            {
                "Transaction ID": txn.transaction_id,
                "Timestamp": txn.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "Amount (INR)": round(txn.amount, 2),
                "Payee": txn.payee_vpa,
                "Payer location": _nearest_city(txn.lat, txn.lon),
                "Payee location": _nearest_city(txn.payee_lat, txn.payee_lon),
                "Risk score": round(assessment.score, 3),
                "Action": _tier_label(assessment.tier),
                "Risk class": _risk_label(assessment.ml_label),
                "_tier": assessment.tier.value,
            }
        )
    return pd.DataFrame.from_records(records)


def _find_pair(
    pairs: list[tuple[Transaction, RiskAssessment]], txn_id: str | None
) -> tuple[Transaction, RiskAssessment] | None:
    if not txn_id:
        return None
    for txn, assessment in pairs:
        if txn.transaction_id == txn_id:
            return txn, assessment
    return None


def _inject_header(paused: bool) -> None:
    live = "paused" if paused else "on"
    label = "Paused" if paused else "Live"
    st.markdown(
        f"""
        <div class="sp-top">
          <div class="sp-brand-wrap">
            <div class="sp-mark">SP</div>
            <div>
              <p class="sp-brand">SentinalPay</p>
              <p class="sp-sub">UPI fraud desk · Legit · Step-up · Hold · Block</p>
            </div>
          </div>
          <div class="sp-live {live}"><span class="sp-dot"></span>{label}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _signal_color(normalized: float) -> str:
    """Same cutovers as the four risk actions, applied to a 0–1 feature signal."""
    if normalized <= 0:
        return COLOR_IDLE
    if normalized <= 0.40:
        return COLOR_LEGIT
    if normalized <= 0.55:
        return COLOR_STEP
    if normalized <= 0.70:
        return COLOR_HOLD
    return COLOR_BLOCK


def _kpi_row(n_queued: int, n_legit: int, n_step: int, n_hold: int, n_block: int, n_risk: int) -> None:
    # Native metrics — custom HTML KPIs double-paint in Streamlit (QUEUEDED / LEGITIT).
    tiles = (
        ("Queued", n_queued, "Live window"),
        ("Legit", n_legit, "Log only"),
        ("Step-up", n_step, "OTP"),
        ("Hold", n_hold, "Delayed"),
        ("Block", n_block, "Lock"),
        ("Risk", n_risk, "Model flag"),
    )
    cols = st.columns(6, gap="small")
    for col, (label, value, hint) in zip(cols, tiles):
        col.metric(label, int(value), help=hint)


def _probability_bars(probabilities: tuple[tuple[str, float], ...]) -> None:
    label_map = {"LEGIT": "Legit", "SUSPICIOUS": "Suspicious", "LIKELY_FRAUD": "Risk"}
    rows = []
    for name, prob in probabilities:
        label = label_map.get(name, name)
        color = RISK_COLORS.get(label, COLOR_IDLE)
        width = max(2.0, float(prob) * 100.0)
        rows.append(
            f'<div class="sp-prob-row">'
            f'<span class="name" style="color:{color}">{label}</span>'
            f'<div class="track"><div class="fill" style="width:{width:.1f}%;background:{color}"></div></div>'
            f'<span class="pct">{prob:.2f}</span></div>'
        )
    st.markdown(f'<div class="sp-prob">{"".join(rows)}</div>', unsafe_allow_html=True)


def _breakdown_chart(contributions: tuple[FeatureContribution, ...]) -> None:
    # Plot a visible stub for zeros so "did not fire" is distinct from "failed to render".
    stub = 0.006
    frame = pd.DataFrame(
        {
            "Feature": [c.name.replace("_", " ") for c in contributions],
            "Weighted score": [c.weighted_score for c in contributions],
            "Bar": [c.weighted_score if c.weighted_score > 0 else stub for c in contributions],
            "Normalized": [c.normalized for c in contributions],
            "Raw": [c.raw_value for c in contributions],
            "Weight": [c.weight for c in contributions],
            "Fired": ["yes" if c.weighted_score > 0 else "no — no contribution" for c in contributions],
            "Color": [_signal_color(c.normalized) for c in contributions],
        }
    )
    fig = px.bar(
        frame,
        x="Bar",
        y="Feature",
        orientation="h",
        color="Color",
        color_discrete_map={
            COLOR_IDLE: COLOR_IDLE,
            COLOR_LEGIT: COLOR_LEGIT,
            COLOR_STEP: COLOR_STEP,
            COLOR_HOLD: COLOR_HOLD,
            COLOR_BLOCK: COLOR_BLOCK,
        },
    )
    fig.update_layout(
        height=360,
        margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color="#c5d0dc",
        font_family="IBM Plex Sans",
        showlegend=False,
        yaxis=dict(autorange="reversed"),
        xaxis_title="Weighted score",
    )
    fig.update_traces(
        customdata=frame[["Weighted score", "Fired"]].to_numpy(),
        hovertemplate="%{y}<br>weighted=%{customdata[0]:.3f}<br>%{customdata[1]}<extra></extra>",
    )
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(
        frame[["Feature", "Weighted score", "Normalized", "Raw", "Weight", "Fired"]],
        hide_index=True,
        use_container_width=True,
        column_config={
            "Weighted score": st.column_config.NumberColumn(format="%.3f"),
            "Normalized": st.column_config.NumberColumn(format="%.2f"),
            "Weight": st.column_config.NumberColumn(format="%.2f"),
        },
    )


def main() -> None:
    _init_state()
    source: SimulatedStream = st.session_state.source
    _inject_header(st.session_state.paused)

    c1, c2, c3, c4 = st.columns((2.2, 1, 1, 1))
    st.session_state.paused = c1.toggle("Pause live feed", value=st.session_state.paused)
    if c2.button("Next batch", use_container_width=True):
        source.next_batch(3)
    if c3.button("Reset stream", use_container_width=True):
        stream = SimulatedStream()
        stream.prime(18)
        st.session_state.source = stream
        st.session_state.selected_txn_id = None
        st.rerun()
    c4.caption("SimulatedStream · swap later for HTTP")

    if not st.session_state.paused:
        source.next_batch(1)

    pairs = source.snapshot()
    if not pairs:
        st.info("Waiting for transactions.")
        return

    scores = [a.score for _, a in pairs]
    n_block = sum(1 for _, a in pairs if getattr(a.tier, "value", a.tier) == RiskTier.BLOCK.value)
    n_hold = sum(1 for _, a in pairs if getattr(a.tier, "value", a.tier) == RiskTier.HOLD.value)
    n_step = sum(1 for _, a in pairs if getattr(a.tier, "value", a.tier) == RiskTier.STEP_UP.value)
    n_legit = sum(1 for _, a in pairs if getattr(a.tier, "value", a.tier) == RiskTier.ALLOW.value)
    n_risk = sum(
        1
        for _, a in pairs
        if a.ml_label is not None and getattr(a.ml_label, "value", a.ml_label) == PaymentRiskLabel.LIKELY_FRAUD.value
    )
    _kpi_row(len(pairs), n_legit, n_step, n_hold, n_block, n_risk)

    feed_col, chart_col = st.columns((1.45, 1), gap="medium")
    frame = _rows(pairs)

    with feed_col:
        st.subheader("Transaction feed")
        visible = frame.drop(columns=["_tier"], errors="ignore")
        st.dataframe(
            visible,
            hide_index=True,
            use_container_width=True,
            height=420,
            column_config={
                "Transaction ID": st.column_config.TextColumn("Transaction ID", width="medium"),
                "Timestamp": st.column_config.TextColumn("Timestamp", width="medium"),
                "Amount (INR)": st.column_config.NumberColumn("Amount (INR)", format="₹%.2f"),
                "Payee": st.column_config.TextColumn("Payee", width="medium"),
                "Payer location": st.column_config.TextColumn("Payer location", width="medium"),
                "Payee location": st.column_config.TextColumn("Payee location", width="medium"),
                "Risk score": st.column_config.NumberColumn("Risk score", format="%.3f"),
                "Action": st.column_config.TextColumn("Action", width="small"),
                "Risk class": st.column_config.TextColumn("Risk class", width="small"),
            },
        )
        options = frame["Transaction ID"].tolist()
        default_id = st.session_state.selected_txn_id
        index = options.index(default_id) if default_id in options else 0
        selected = st.selectbox("Inspect transaction", options, index=index)
        st.session_state.selected_txn_id = selected

    with chart_col:
        st.subheader("Risk-score distribution")
        hist = px.histogram(
            pd.DataFrame({"score": scores}),
            x="score",
            nbins=16,
            color_discrete_sequence=["#3ee0c5"],
        )
        hist.update_layout(
            height=420,
            margin=dict(l=40, r=16, t=24, b=48),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font_color="#c5d0dc",
            font_family="IBM Plex Sans",
            xaxis_title="Risk score",
            yaxis_title="Count",
            bargap=0.08,
            yaxis=dict(dtick=1, tick0=0, rangemode="tozero", tickformat="d"),
            xaxis=dict(range=[-0.02, 1.02], dtick=0.2, ticks="outside"),
        )
        hist.add_vline(x=0.40, line_dash="dot", line_color=COLOR_LEGIT)
        hist.add_vline(x=0.55, line_dash="dot", line_color=COLOR_STEP)
        hist.add_vline(x=0.70, line_dash="dot", line_color=COLOR_BLOCK)
        st.plotly_chart(hist, use_container_width=True)

    pair = _find_pair(pairs, st.session_state.selected_txn_id)
    if pair is not None:
        txn, assessment = pair
        badge = _tier_label(assessment.tier)
        action = _tier_action(assessment.tier)
        st.subheader(f"Case {txn.transaction_id} · {assessment.score:.3f}")
        loc_l, loc_r = st.columns(2)
        loc_l.caption("Action")
        loc_l.write(f"{badge} — {action}")
        loc_r.caption("Risk class")
        loc_r.write(_risk_label(assessment.ml_label))
        pay_l, pay_r = st.columns(2)
        pay_l.caption("Payer location")
        pay_l.write(_nearest_city(txn.lat, txn.lon))
        pay_r.caption("Payee location")
        pay_r.write(_nearest_city(txn.payee_lat, txn.payee_lon))
        st.caption(
            f"Amount ₹{txn.amount:,.2f} · {txn.timestamp.strftime('%Y-%m-%d %H:%M:%S')} · "
            f"purpose={txn.purpose or 'unknown'} · payee shown for demo only."
        )
        if assessment.ml_label is not None:
            _probability_bars(assessment.ml_probabilities)
        _breakdown_chart(assessment.contributions)

    if not st.session_state.paused:
        time.sleep(REFRESH_SECONDS)
        st.rerun()


if __name__ == "__main__":
    main()
