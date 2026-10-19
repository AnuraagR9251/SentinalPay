"""SentinalPay analyst dashboard.

Talks only to a `TransactionSource`. Default is `HttpTransactionSource`
(GET /transactions from the scoring API the payment app already POSTs to).

# TODO: apply rate limiting here before production use
# TODO: persist via parameterized queries / ORM only — never string-formatted SQL
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from data_simulator import HttpTransactionSource  # type: ignore  # noqa: E402
except ImportError:
    from dashboard.data_simulator import HttpTransactionSource  # noqa: E402
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
REFRESH_SECONDS = 8.0

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
    if "source" not in st.session_state or not hasattr(st.session_state.source, "pull"):
        source = HttpTransactionSource()
        source.pull()
        st.session_state.source = source
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
                "Canonical": assessment.canonical_decision or "—",
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
    # Native widgets — custom HTML double-paints in Streamlit (SentinalPayay / LIVEVE).
    brand, live = st.columns((5, 1))
    brand.markdown("### SentinalPay")
    brand.caption("Sandbox desk · polls GET /transactions · not a bank feed")
    live.markdown("**Paused**" if paused else "**LIVE**")


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


def _kpi_row(n_queued: int, n_legit: int, n_step: int, n_hold: int, n_block: int, n_review: int) -> None:
    # Native metrics — custom HTML KPIs double-paint in Streamlit (QUEUEDED / LEGITIT).
    tiles = (
        ("Queued", n_queued, "Live window"),
        ("Allow", n_legit, "Canonical ALLOW / legacy Allow"),
        ("Step-up", n_step, "Policy action, not a canonical decision"),
        ("Hold", n_hold, "Legacy HOLD (canonical REVIEW unless STEP_UP)"),
        ("Block", n_block, "Canonical BLOCK"),
        ("Review", n_review, "Canonical REVIEW count"),
    )
    cols = st.columns(6, gap="small")
    for col, (label, value, hint) in zip(cols, tiles):
        col.metric(label, int(value), help=hint)


def _opt_prob(value: float | None, available: bool) -> str:
    if not available or value is None:
        return "unavailable"
    return f"{value:.3f}"


def _risk_distribution_chart(pairs: list[tuple[Transaction, RiskAssessment]]) -> None:
    """Histogram colored by the backend action, not invented score bands."""
    if not pairs:
        st.info("No scores yet.")
        return
    frame = pd.DataFrame(
        {
            "score": [assessment.score for _, assessment in pairs],
            "Action": [_tier_label(assessment.tier) for _, assessment in pairs],
        }
    )
    color_map = {
        "Legit": COLOR_LEGIT,
        "Step-up": COLOR_STEP,
        "Hold": COLOR_HOLD,
        "Block": COLOR_BLOCK,
    }
    hist = px.histogram(
        frame,
        x="score",
        color="Action",
        color_discrete_map=color_map,
        category_orders={"Action": ["Legit", "Step-up", "Hold", "Block"]},
        nbins=16,
    )
    hist.update_layout(
        height=420,
        margin=dict(l=40, r=16, t=24, b=48),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color="#c5d0dc",
        font_family="IBM Plex Sans",
        xaxis_title="Risk score (0–1, from API)",
        yaxis_title="Count",
        bargap=0.08,
        legend_title_text="",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        yaxis=dict(dtick=1, tick0=0, rangemode="tozero", tickformat="d"),
        xaxis=dict(range=[0, 1], dtick=0.2, ticks="outside"),
    )
    st.plotly_chart(hist, use_container_width=True)


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


def _render_desk() -> None:
    source: HttpTransactionSource = st.session_state.source
    if not st.session_state.paused:
        source.next_batch(1)

    pairs = source.snapshot()
    err = getattr(source, "last_error", None)
    if err:
        st.warning(
            f"Score API error ({err}). Showing last successful feed if any. "
            "Start `uvicorn api.main:app --port 8000`."
        )
    if not pairs:
        if err:
            st.error("No cached cases. Reconnect once the API is up.")
        elif getattr(source, "last_ok_at", None):
            st.info("Feed is empty. Score a sandbox payment in the React app.")
        else:
            st.info("Waiting for the first successful GET /transactions.")
        return

    n_block = sum(1 for _, a in pairs if getattr(a.tier, "value", a.tier) == RiskTier.BLOCK.value)
    n_hold = sum(1 for _, a in pairs if getattr(a.tier, "value", a.tier) == RiskTier.HOLD.value)
    n_step = sum(1 for _, a in pairs if getattr(a.tier, "value", a.tier) == RiskTier.STEP_UP.value)
    n_legit = sum(1 for _, a in pairs if getattr(a.tier, "value", a.tier) == RiskTier.ALLOW.value)
    n_review = sum(1 for _, a in pairs if a.canonical_decision == "REVIEW")
    _kpi_row(len(pairs), n_legit, n_step, n_hold, n_block, n_review)

    feed_col, case_col = st.columns((1.45, 1), gap="medium")
    frame = _rows(pairs)
    feed_cols = [
        "Transaction ID",
        "Timestamp",
        "Amount (INR)",
        "Payee",
        "Risk score",
        "Canonical",
        "Action",
    ]
    visible = frame[feed_cols]

    with feed_col:
        st.subheader("Transaction feed")
        st.caption("Click a row to load the case.")
        event = st.dataframe(
            visible,
            hide_index=True,
            use_container_width=True,
            height=320,
            on_select="rerun",
            selection_mode="single-row",
            key="feed_table",
            column_config={
                "Transaction ID": st.column_config.TextColumn("ID", width="small"),
                "Timestamp": st.column_config.TextColumn("Time", width="small"),
                "Amount (INR)": st.column_config.NumberColumn("Amount", format="₹%.2f", width="small"),
                "Payee": st.column_config.TextColumn("Payee", width="medium"),
                "Risk score": st.column_config.NumberColumn("Score", format="%.3f", width="small"),
                "Canonical": st.column_config.TextColumn("Canonical", width="small"),
                "Action": st.column_config.TextColumn("Action", width="small"),
            },
        )
        rows = list(getattr(getattr(event, "selection", None), "rows", None) or [])
        if rows:
            picked = str(visible.iloc[int(rows[0])]["Transaction ID"])
            if picked != st.session_state.selected_txn_id:
                st.session_state.selected_txn_id = picked
                st.session_state.paused = True
                st.rerun()
        if not st.session_state.selected_txn_id and not visible.empty:
            st.session_state.selected_txn_id = str(visible.iloc[0]["Transaction ID"])

    pair = _find_pair(pairs, st.session_state.selected_txn_id)
    with case_col:
        if pair is None:
            st.subheader("Case")
            st.info("Click a feed row to load payee, locations, and feature scores.")
        else:
            txn, assessment = pair
            badge = _tier_label(assessment.tier)
            action = _tier_action(assessment.tier)
            st.subheader(f"Case {txn.transaction_id} · {assessment.score:.3f}")
            loc_l, loc_r = st.columns(2)
            loc_l.caption("Canonical decision")
            loc_l.write(assessment.canonical_decision or "—")
            loc_r.caption("Legacy / policy action")
            loc_r.write(f"{badge} — {action}")
            pay_l, pay_r = st.columns(2)
            pay_l.caption("Payer location")
            pay_l.write(
                "omitted" if txn.lat is None or txn.lon is None else _nearest_city(txn.lat, txn.lon)
            )
            pay_r.caption("Payee location")
            pay_r.write(
                "unavailable"
                if txn.payee_lat is None or txn.payee_lon is None
                else _nearest_city(txn.payee_lat, txn.payee_lon)
            )
            who_l, who_r = st.columns(2)
            who_l.caption("Payee")
            who_l.write(txn.payee_vpa)
            who_r.caption("Payer")
            who_r.write(txn.user_id)
            st.caption(
                f"Amount ₹{txn.amount:,.2f} · {txn.timestamp.strftime('%Y-%m-%d %H:%M:%S')} · "
                f"purpose={txn.purpose or 'unknown'}"
            )
            if assessment.ml_available is True:
                xgb_txt = _opt_prob(assessment.p_xgb, True)
            elif assessment.ml_available is False:
                xgb_txt = "unavailable"
            else:
                xgb_txt = "unknown"
            canonical = assessment.canonical_risk_score
            canonical_txt = "—" if canonical is None else f"{int(canonical)}/100"
            if assessment.ml_available is True:
                xgb_label = assessment.ml_note or "PaySim-trained; not a UPI-calibrated probability"
            else:
                xgb_label = assessment.ml_note or "model unavailable"
            st.caption(
                f"P_xgb={xgb_txt} ({xgb_label}) · "
                f"canonical {canonical_txt} · "
                f"legacy 0–1 display={assessment.score:.3f} · "
                f"P_ae={_opt_prob(assessment.p_ae, assessment.ae_available)} · "
                f"P_graph={_opt_prob(assessment.p_graph, assessment.graph_available)}"
            )
            if assessment.ml_label is not None and assessment.ml_probabilities:
                _probability_bars(assessment.ml_probabilities)
            elif assessment.ml_label is None:
                st.caption("No backend fraud class on this row — none invented.")

    if pair is not None:
        st.subheader("Feature breakdown")
        _breakdown_chart(pair[1].contributions)

    st.subheader("Risk-score distribution")
    _risk_distribution_chart(pairs)


@st.experimental_fragment(run_every=REFRESH_SECONDS)
def _live_desk() -> None:
    _render_desk()


def main() -> None:
    _init_state()
    source: HttpTransactionSource = st.session_state.source
    _inject_header(st.session_state.paused)

    c1, c2, c3, c4 = st.columns((2.2, 1, 1, 1))
    st.session_state.paused = c1.toggle("Pause live feed", value=st.session_state.paused)
    if c2.button("Refresh now", use_container_width=True):
        source.pull()
    if c3.button("Clear view", use_container_width=True):
        st.session_state.selected_txn_id = None
        st.session_state.pop("feed_table", None)
        source.pull()
        st.rerun()
    ok_at = getattr(source, "last_ok_at", None)
    err = getattr(source, "last_error", None)
    if err == "RateLimited":
        c4.caption("Rate limited · holding last feed")
    elif err:
        c4.caption(f"Disconnected · {err}")
    elif ok_at:
        c4.caption(f"Connected · {ok_at.strftime('%H:%M:%S UTC')}")
    else:
        c4.caption(f"GET {source.base_url}/transactions")

    if st.session_state.paused:
        _render_desk()
    else:
        _live_desk()


if __name__ == "__main__":
    main()
