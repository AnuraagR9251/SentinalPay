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

# Streamlit caches imports across reruns. Evict detection only — never
# `dashboard`, because this file is already running as dashboard.app.
for _mod in list(sys.modules):
    if _mod == "detection" or _mod.startswith("detection."):
        del sys.modules[_mod]

from data_simulator import SimulatedStream  # noqa: E402
from detection.models import (  # noqa: E402
    FeatureContribution,
    PaymentRiskLabel,
    RiskAssessment,
    RiskTier,
    Transaction,
)

# Four architecture actions: Legit / Step-up / Hold / Block
TIER_COLORS = {
    RiskTier.ALLOW: "#1B7F4E",
    RiskTier.STEP_UP: "#C47B17",
    RiskTier.HOLD: "#B45309",
    RiskTier.BLOCK: "#C0392B",
}
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
    "Legit": "#1B7F4E",
    "Suspicious": "#C47B17",
    "Risk": "#C0392B",
    "—": "#4a5560",
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
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      .stApp { background: #0f1419; color: #e8edf2; }
      h1, h2, h3 { letter-spacing: -0.02em; }
      div[data-testid="stMetricValue"] { font-variant-numeric: tabular-nums; }
    </style>
    """,
    unsafe_allow_html=True,
)


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
                "Action": TIER_LABELS[assessment.tier],
                "Risk class": RISK_LABELS.get(assessment.ml_label, "—") if assessment.ml_label else "—",
                "_tier": assessment.tier.value,
            }
        )
    return pd.DataFrame.from_records(records)


def _style_tiers(df: pd.DataFrame) -> "pd.io.formats.style.Styler":
    def color_tier(value: str) -> str:
        mapping = {
            "Legit": "background-color: #1B7F4E; color: #ffffff;",
            "Step-up": "background-color: #C47B17; color: #ffffff;",
            "Hold": "background-color: #B45309; color: #ffffff;",
            "Block": "background-color: #C0392B; color: #ffffff;",
            "Suspicious": "background-color: #C47B17; color: #ffffff;",
            "Risk": "background-color: #C0392B; color: #ffffff;",
        }
        return mapping.get(value, "")

    visible = df.drop(columns=["_tier"], errors="ignore")
    styled = visible.style.map(color_tier, subset=["Action"])
    if "Risk class" in visible.columns:
        styled = styled.map(color_tier, subset=["Risk class"])
    return styled.format({"Amount (INR)": "₹{:,.2f}", "Risk score": "{:.3f}"})


def _find_pair(
    pairs: list[tuple[Transaction, RiskAssessment]], txn_id: str | None
) -> tuple[Transaction, RiskAssessment] | None:
    if not txn_id:
        return None
    for txn, assessment in pairs:
        if txn.transaction_id == txn_id:
            return txn, assessment
    return None


def _breakdown_chart(contributions: tuple[FeatureContribution, ...]) -> None:
    frame = pd.DataFrame(
        {
            "Feature": [c.name.replace("_", " ") for c in contributions],
            "Weighted score": [c.weighted_score for c in contributions],
            "Normalized": [c.normalized for c in contributions],
            "Raw": [c.raw_value for c in contributions],
            "Weight": [c.weight for c in contributions],
        }
    )
    fig = px.bar(
        frame,
        x="Weighted score",
        y="Feature",
        orientation="h",
        color="Weighted score",
        color_continuous_scale=["#1B7F4E", "#C47B17", "#C0392B"],
        range_color=(0, 0.2),
    )
    fig.update_layout(
        height=360,
        margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color="#e8edf2",
        coloraxis_showscale=False,
        yaxis=dict(autorange="reversed"),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.dataframe(
        frame,
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

    st.title("SentinalPay")
    st.caption("UPI fraud desk · four actions: Legit · Step-up · Hold · Block")

    sidebar = st.sidebar
    sidebar.header("Feed controls")
    st.session_state.paused = sidebar.checkbox("Pause live feed", value=st.session_state.paused)
    cols = sidebar.columns(2)
    if cols[0].button("Next batch", use_container_width=True):
        source.next_batch(3)
    if cols[1].button("Reset stream", use_container_width=True):
        stream = SimulatedStream()
        stream.prime(18)
        st.session_state.source = stream
        st.session_state.selected_txn_id = None
        st.rerun()

    sidebar.markdown(
        "Data source: `SimulatedStream`. To use a real API later, "
        "construct `HttpTransactionSource(base_url)` in `_init_state`."
    )

    if not st.session_state.paused:
        source.next_batch(1)

    pairs = source.snapshot()
    if not pairs:
        st.info("Waiting for transactions.")
        return

    scores = [a.score for _, a in pairs]
    n_block = sum(1 for _, a in pairs if a.tier is RiskTier.BLOCK)
    n_hold = sum(1 for _, a in pairs if a.tier is RiskTier.HOLD)
    n_step = sum(1 for _, a in pairs if a.tier is RiskTier.STEP_UP)
    n_legit = sum(1 for _, a in pairs if a.tier is RiskTier.ALLOW)
    n_risk = sum(1 for _, a in pairs if a.ml_label is PaymentRiskLabel.LIKELY_FRAUD)

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("In buffer", f"{len(pairs)}")
    m2.metric("Legit", f"{n_legit}")
    m3.metric("Step-up", f"{n_step}")
    m4.metric("Hold", f"{n_hold}")
    m5.metric("Block", f"{n_block}")
    m6.metric("Risk", f"{n_risk}")

    feed_col, chart_col = st.columns((1.45, 1))
    frame = _rows(pairs)

    with feed_col:
        st.subheader("Transaction feed")
        st.dataframe(_style_tiers(frame), use_container_width=True, height=420)
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
            color_discrete_sequence=["#3D8BFF"],
        )
        hist.update_layout(
            height=420,
            margin=dict(l=10, r=10, t=10, b=10),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font_color="#e8edf2",
            xaxis_title="Risk score",
            yaxis_title="Count",
            bargap=0.08,
        )
        hist.add_vline(x=0.40, line_dash="dot", line_color="#1B7F4E")
        hist.add_vline(x=0.55, line_dash="dot", line_color="#C47B17")
        hist.add_vline(x=0.70, line_dash="dot", line_color="#C0392B")
        st.plotly_chart(hist, use_container_width=True)

    pair = _find_pair(pairs, st.session_state.selected_txn_id)
    if pair is not None:
        txn, assessment = pair
        st.subheader(f"Why {txn.transaction_id} scored {assessment.score:.3f}")
        badge = TIER_LABELS[assessment.tier]
        action = TIER_ACTIONS[assessment.tier]
        st.markdown(
            f"<span style='background:{TIER_COLORS[assessment.tier]};color:#fff;"
            f"padding:4px 10px;border-radius:4px;font-weight:600'>{badge}</span>"
            f"<span style='margin-left:10px;opacity:0.85'>{action}</span>",
            unsafe_allow_html=True,
        )
        loc_a, loc_b = st.columns(2)
        loc_a.markdown(f"**Payer location:** {_nearest_city(txn.lat, txn.lon)}")
        loc_b.markdown(f"**Payee location:** {_nearest_city(txn.payee_lat, txn.payee_lon)}")
        st.caption(
            f"Amount ₹{txn.amount:,.2f} · purpose={txn.purpose or 'unknown'} · "
            "payee shown for demo only · logs never contain this row's PII."
        )
        if assessment.ml_label is not None:
            risk_name = RISK_LABELS[assessment.ml_label]
            st.markdown(
                f"**Risk class:** <span style='background:{RISK_COLORS[risk_name]};color:#fff;"
                f"padding:3px 8px;border-radius:4px'>{risk_name}</span>",
                unsafe_allow_html=True,
            )
            label_map = {"LEGIT": "Legit", "SUSPICIOUS": "Suspicious", "LIKELY_FRAUD": "Risk"}
            proba_df = pd.DataFrame(
                [
                    {"Risk class": label_map.get(name, name), "Probability": prob}
                    for name, prob in assessment.ml_probabilities
                ]
            )
            st.dataframe(
                proba_df,
                hide_index=True,
                use_container_width=True,
                column_config={"Probability": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f")},
            )
        _breakdown_chart(assessment.contributions)

    if not st.session_state.paused:
        time.sleep(REFRESH_SECONDS)
        st.rerun()


if __name__ == "__main__":
    main()
