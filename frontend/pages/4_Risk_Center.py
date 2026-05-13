"""Risk desk page for FTMO supervision."""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from components.platform import (
    api_get,
    apply_plotly_theme,
    chip_html,
    format_money,
    format_pct,
    init_platform,
    inject_global_styles,
    render_data_table,
    render_empty_panel,
    render_metric_card,
    render_page_header,
    render_sidebar,
    render_surface,
    require_session,
)


st.set_page_config(page_title="Risk Center | XAUUSD", layout="wide")
init_platform()
inject_global_styles()
render_sidebar("Risk Center")

render_page_header(
    kicker="Risk Oversight",
    title="Risk Center",
    copy=(
        "A rebuilt risk desk for checking FTMO posture, downside room and scenario impact before new exposure is added. "
        "The page is structured for risk decisions, not visual novelty."
    ),
)

require_session()

snapshot_payload = api_get("/risk/status")
if snapshot_payload is None:
    render_empty_panel("Data service unavailable", "The risk desk could not reach the local trading service.")
    st.stop()

if snapshot_payload.get("_auth_error"):
    render_empty_panel("Session expired", "Re-authenticate from the sidebar to continue working with risk tools.")
    st.stop()

snapshot = snapshot_payload.get("data", {})
ftmo = snapshot.get("ftmo_status", {})

top_cols = st.columns(4)
top_cards = [
    ("Equity", format_money(snapshot.get("equity", 0.0)), "Current monitored equity."),
    ("Stress Score", f"{float(snapshot.get('stress_score', 0.0)):.0f} / 100", "Pressure estimate from the current snapshot."),
    ("Fail Probability", format_pct(snapshot.get("fail_probability", 0.0)), "Heuristic downside likelihood."),
    ("Open Positions", str(snapshot.get("open_positions", 0)), "Current live exposure count."),
]
for col, card in zip(top_cols, top_cards):
    with col:
        render_metric_card(*card)

current_col, sim_col = st.columns([0.96, 1.04], gap="large")

with current_col:
    st.markdown("### Current FTMO Posture")
    if ftmo:
        risk_level = str(ftmo.get("risk_level", "green")).upper()
        tone = "bad" if risk_level == "RED" else "warn" if risk_level == "YELLOW" else "ok"
        st.markdown(chip_html(f"Risk level: {risk_level}", tone), unsafe_allow_html=True)
        current_rows = {
            "Daily loss used": format_money(ftmo.get("daily_loss_used", 0.0)),
            "Daily remaining": format_money(ftmo.get("daily_remaining", 0.0)),
            "Daily buffer": format_pct(ftmo.get("daily_buffer_pct", 0.0), assume_fraction=False),
            "Total loss used": format_money(ftmo.get("total_loss_used", 0.0)),
            "Total remaining": format_money(ftmo.get("total_remaining", 0.0)),
            "Total buffer": format_pct(ftmo.get("total_buffer_pct", 0.0), assume_fraction=False),
            "Daily status": "Compliant" if ftmo.get("daily_ok") else "At risk",
            "Total status": "Compliant" if ftmo.get("total_ok") else "At risk",
        }
        render_data_table([{"Metric": key, "Value": value} for key, value in current_rows.items()])
    else:
        render_empty_panel("No FTMO posture available", "The service has not returned a usable FTMO status snapshot yet.")

    st.markdown("### Risk Doctrine")
    render_surface(
        "Before Adding Exposure",
        "Use this desk to decide whether the next trade fits inside the current loss budget and execution pressure.",
        points=[
            "Check remaining daily room before any new position.",
            "Compare projected risk to day-start equity, not only current balance.",
            "Treat red posture as a stop condition, not a warning label.",
        ],
        kicker="Procedure",
    )

with sim_col:
    st.markdown("### Buffer Simulation")
    default_equity = float(snapshot.get("equity", 160000.0) or 160000.0)
    default_day_start = float(snapshot.get("day_start_equity", default_equity) or default_equity)
    default_risk = float(snapshot.get("estimated_trade_risk", 400.0) or 400.0)

    with st.form("ftmo_buffer_simulator"):
        field_col1, field_col2, field_col3 = st.columns(3)
        equity = field_col1.number_input("Current equity", value=default_equity, step=500.0)
        day_start_equity = field_col2.number_input("Day-start equity", value=default_day_start, step=500.0)
        estimated_trade_risk = field_col3.number_input("Estimated trade risk", value=default_risk, step=100.0)
        submitted = st.form_submit_button("Run Simulation", type="primary", use_container_width=True)

    if submitted:
        simulation_payload = api_get(
            "/risk/ftmo",
            params={
                "equity": equity,
                "day_start_equity": day_start_equity,
                "estimated_trade_risk": estimated_trade_risk,
            },
        )
        if simulation_payload is None:
            render_empty_panel("Simulation unavailable", "The risk engine could not be reached for this scenario.")
        elif simulation_payload.get("_auth_error"):
            render_empty_panel("Session expired", "Re-authenticate from the sidebar before running a simulation.")
        else:
            result = simulation_payload.get("data", {})
            level = str(result.get("risk_level", "green")).upper()
            tone = "bad" if level == "RED" else "warn" if level == "YELLOW" else "ok"
            st.markdown(chip_html(f"Projected level: {level}", tone), unsafe_allow_html=True)

            summary_cols = st.columns(4)
            summary_cards = [
                ("Daily Remaining", format_money(result.get("daily_remaining", 0.0)), format_pct(result.get("daily_buffer_pct", 0.0), assume_fraction=False)),
                ("Total Remaining", format_money(result.get("total_remaining", 0.0)), format_pct(result.get("total_buffer_pct", 0.0), assume_fraction=False)),
                ("Daily Used", format_money(result.get("daily_loss_used", 0.0)), "Consumption against day-start equity."),
                ("Total Used", format_money(result.get("total_loss_used", 0.0)), "Consumption against starting capital."),
            ]
            for col, card in zip(summary_cols, summary_cards):
                with col:
                    render_metric_card(*card)

            gauge_cols = st.columns(2)
            gauge_specs = [
                ("Daily buffer consumed", 100 - float(result.get("daily_buffer_pct", 0.0))),
                ("Total buffer consumed", 100 - float(result.get("total_buffer_pct", 0.0))),
            ]
            for col, (label, pct_value) in zip(gauge_cols, gauge_specs):
                color = "#c55a67" if pct_value > 70 else "#b97f2f" if pct_value > 40 else "#1d8b61"
                fig = go.Figure(
                    go.Indicator(
                        mode="gauge+number",
                        value=max(0.0, min(100.0, pct_value)),
                        number={"suffix": "%"},
                        title={"text": label},
                        gauge={
                            "axis": {"range": [0, 100]},
                            "bar": {"color": color},
                            "steps": [
                                {"range": [0, 40], "color": "#deefe8"},
                                {"range": [40, 70], "color": "#f3e8d9"},
                                {"range": [70, 100], "color": "#f6dee2"},
                            ],
                        },
                    )
                )
                apply_plotly_theme(fig)
                fig.update_layout(height=260)
                col.plotly_chart(fig, use_container_width=True)
