"""Live monitoring page for the expert desk."""
from __future__ import annotations

import time
from datetime import datetime

import pandas as pd
import streamlit as st

from components.platform import (
    api_get,
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


st.set_page_config(page_title="Live Dashboard | XAUUSD", layout="wide")
init_platform()
inject_global_styles()
render_sidebar("Live Dashboard")

render_page_header(
    kicker="Execution Monitoring",
    title="Live Dashboard",
    copy=(
        "A rebuilt live desk for supervising account condition, signal posture and open exposure with less visual noise. "
        "Every block is aimed at fast reading during active market hours."
    ),
)

require_session()

risk_data = api_get("/risk/status")
live_data = api_get("/dashboard/live")
signal_data = api_get("/signals/live")
positions_data = api_get("/signals/positions/open")

if risk_data is None and live_data is None:
    render_empty_panel("Data service unavailable", "The live dashboard could not reach the local trading service.")
    st.stop()

if (risk_data or {}).get("_auth_error") or (live_data or {}).get("_auth_error"):
    render_empty_panel("Session expired", "Re-authenticate from the sidebar to continue monitoring.")
    st.stop()

snapshot = (risk_data or {}).get("data", {})
ftmo = snapshot.get("ftmo_status", {})
bot_state = (live_data or {}).get("data", {}).get("bot_state", {}) if live_data else {}
positions = (positions_data or {}).get("data", []) if positions_data else []
signal = (signal_data or {}).get("data") if signal_data and signal_data.get("data") else None

top_cols = st.columns(5)
top_cards = [
    ("Equity", format_money(snapshot.get("equity", 0.0)), "Current monitored account equity."),
    ("Daily Buffer", format_pct(ftmo.get("daily_buffer_pct", 0.0), assume_fraction=False), "Distance to the FTMO daily limit."),
    ("Total Buffer", format_pct(ftmo.get("total_buffer_pct", 0.0), assume_fraction=False), "Distance to the total max-loss threshold."),
    ("Stress Score", f"{float(snapshot.get('stress_score', 0.0)):.0f} / 100", "Heuristic pressure estimate for current conditions."),
    ("Fail Probability", format_pct(snapshot.get("fail_probability", 0.0)), "Modelled downside fragility under current state."),
]
for col, card in zip(top_cols, top_cards):
    with col:
        render_metric_card(*card)

st.markdown("### Session View")
overview_left, overview_right = st.columns([1.05, 0.95], gap="large")

with overview_left:
    if snapshot:
        risk_level = str(ftmo.get("risk_level", "green")).upper()
        tone = "bad" if risk_level == "RED" else "warn" if risk_level == "YELLOW" else "ok"
        st.markdown(chip_html(f"FTMO risk level: {risk_level}", tone), unsafe_allow_html=True)
        status_rows = {
            "Balance": format_money(snapshot.get("balance", 0.0)),
            "Day-start equity": format_money(snapshot.get("day_start_equity", 0.0)),
            "Estimated trade risk": format_money(snapshot.get("estimated_trade_risk", 0.0)),
            "Open positions": str(snapshot.get("open_positions", 0)),
            "Session active": "Yes" if snapshot.get("session_active") else "No",
            "Spread points": f"{float(snapshot.get('spread_points', 0.0)):.1f}",
        }
        render_data_table(pd.DataFrame(status_rows.items(), columns=["Metric", "Value"]))
    else:
        render_empty_panel("No risk snapshot available", "The trading service has not published a current account snapshot yet.")

    st.markdown("### Open Positions")
    if positions:
        positions_df = pd.DataFrame(positions)
        if "unrealized_pnl" in positions_df.columns:
            positions_df["unrealized_pnl"] = positions_df["unrealized_pnl"].map(format_money)
        for price_col in ["open_price", "current_price", "stop_loss", "take_profit"]:
            if price_col in positions_df.columns:
                positions_df[price_col] = positions_df[price_col].map(lambda value: f"{float(value):,.2f}")
        render_data_table(positions_df)
    else:
        render_empty_panel("No active exposure", "There are currently no open MT5 positions for the monitored account.")

with overview_right:
    st.markdown("### Signal Watch")
    if signal:
        signal_tone = "ok" if str(signal.get("side", "")).lower() == "buy" else "warn"
        st.markdown(
            chip_html(f"{signal.get('entry_label', 'Signal')} | {str(signal.get('side', '')).upper()}", signal_tone),
            unsafe_allow_html=True,
        )
        signal_rows = {
            "Trigger time": str(signal.get("trigger_time", "-")),
            "Reference price": f"{float(signal.get('reference_price', 0.0)):,.2f}",
            "ATR": f"{float(signal.get('atr_value', 0.0)):,.2f}",
            "Reason": str(signal.get("reason", "-")),
        }
        render_data_table(pd.DataFrame(signal_rows.items(), columns=["Field", "Value"]))
    else:
        render_surface(
            "No Qualified Signal",
            "The live engine is available, but the active filters are not confirming a new trade setup right now.",
            points=[
                "Market conditions are being monitored continuously.",
                "No manual action is required if your rules remain unchanged.",
                "Keep attention on risk state until a qualified signal appears.",
            ],
            kicker="Signal State",
        )

    st.markdown("### Bot State")
    if bot_state:
        render_data_table(pd.DataFrame(bot_state.items(), columns=["Field", "Value"]))
    else:
        render_surface(
            "No Bot State Published",
            "The execution process may still be warming up or the local state file has not been written yet.",
            points=[
                "Confirm the execution service is running.",
                "Wait for the next state write cycle.",
                "Re-check service health from the sidebar if needed.",
            ],
            kicker="Service State",
        )

st.caption(f"Last reviewed: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")

if st.session_state.get("auto_refresh"):
    time.sleep(30)
    st.rerun()
