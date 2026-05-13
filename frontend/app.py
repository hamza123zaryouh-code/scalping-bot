"""Streamlit entry point for the XAUUSD expert desk."""
from __future__ import annotations

import subprocess
import sys

import pandas as pd
import streamlit as st

from components.platform import (
    api_get,
    chip_html,
    current_mode,
    format_money,
    init_platform,
    inject_global_styles,
    load_bot_analysis,
    load_bot_state,
    load_recent_bot_messages,
    render_data_table,
    render_metric_card,
    render_page_header,
    render_sidebar,
    render_surface,
)


st.set_page_config(
    page_title="XAUUSD Expert Desk",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={"About": "XAUUSD expert trading desk"},
)

init_platform()
inject_global_styles()
render_sidebar("Overview")

render_page_header(
    kicker="Executive Overview",
    title="XAUUSD Expert Trading Desk",
    copy=(
        "This overview now explains the real bot behavior instead of showing generic text. "
        "It reads local config, bot state and recent runtime activity so you can understand what the engine is doing."
    ),
)

mode = current_mode().upper()
service_health = api_get("/health", auth_required=False) or {}
service_state = "Online" if service_health.get("status") == "healthy" else "Offline"
access_state = "Open" if st.session_state.get("jwt_token") else "Restricted"
refresh_state = "Enabled" if st.session_state.get("auto_refresh") else "Manual"
analysis = load_bot_analysis()
bot_state = load_bot_state()
recent_messages = load_recent_bot_messages(limit=5)

summary_cols = st.columns(4)
summary_cards = [
    ("Execution Mode", mode, "Active environment loaded from local configuration."),
    ("Symbol and Frame", f"{analysis['symbol']} | {analysis['timeframe']}", "Instrument and chart interval used by the bot."),
    ("Risk Per Trade", f"{analysis['risk_per_trade_pct']:.2f}%", "Configured position risk before FTMO buffer checks."),
    ("Last Engine Event", "Scanning" if "No new qualified signal" in analysis["last_event"] else "Updated", analysis["last_event"][:80]),
]
for col, card in zip(summary_cols, summary_cards):
    with col:
        render_metric_card(*card)

status_cols = st.columns(4)
status_cards = [
    ("Data Service", service_state, "Connectivity state of the local API service."),
    ("Session Access", access_state, "Authentication gate for protected trading endpoints."),
    ("Refresh Policy", refresh_state, "Monitoring cadence for live desk supervision."),
    ("Heartbeat", analysis["last_heartbeat_time"] or "No heartbeat", "Latest bot heartbeat written to local state."),
]
for col, card in zip(status_cols, status_cards):
    with col:
        render_metric_card(*card)

st.markdown("### Strategy Analysis")
strategy_cols = st.columns(3, gap="large")
with strategy_cols[0]:
    render_surface(
        "Signal Logic",
        "The live engine evaluates closed bars and only qualifies a trade when bias, momentum and volume agree.",
        points=[
            f"M5 bias must align before a {analysis['symbol']} entry is allowed.",
            "EMA 8 and EMA 21 cross is used as the trigger event.",
            "Price must confirm against EMA 50 before entry is accepted.",
            f"Volume must beat the moving average by {analysis['volume_multiplier']:.2f} times.",
        ],
        kicker="Entry Model",
    )
with strategy_cols[1]:
    render_surface(
        "Execution Guardrails",
        "The bot is intentionally conservative and blocks trades when operational constraints are not satisfied.",
        points=[
            f"Risk per trade is capped at {analysis['risk_per_trade_pct']:.2f} percent.",
            f"Stop loss uses {analysis['sl_atr']:.1f} ATR and target uses {analysis['tp_atr']:.1f} ATR.",
            f"Maximum open positions: {analysis['max_open_positions']}.",
            f"Cooldown between duplicate signals: {analysis['cooldown_minutes']} minutes.",
        ],
        kicker="Risk Logic",
    )
with strategy_cols[2]:
    render_surface(
        "Session and Limits",
        "The runtime window and FTMO boundaries define when the bot is even allowed to participate.",
        points=[
            f"Trading window: {analysis['trading_window']}.",
            f"Allowed weekdays: {analysis['allowed_days']}.",
            f"Maximum spread filter: {analysis['max_spread_points']:.1f} points.",
            f"History bars loaded each cycle: {analysis['history_bars']}.",
        ],
        kicker="Session Rules",
    )

st.markdown("### Runtime Analysis")
left, right = st.columns([1.15, 0.85], gap="large")
with left:
    runtime_rows = [
        ("Current trading day", analysis["current_trading_day"] or "No state"),
        ("Day-start equity", format_money(analysis["day_start_equity"]) if analysis["day_start_equity"] else "Unknown"),
        ("Last processed bar", analysis["last_processed_bar"] or "No bar processed"),
        ("Last signal", analysis["last_signal"]),
        ("Last trade time", analysis["last_trade_time"] or "No trade recorded"),
        ("Telegram ready", "Yes" if analysis["telegram_ready"] else "No"),
        ("Telegram sent today", str(analysis["telegram_messages_sent"])),
        ("Order comment", analysis["order_comment"]),
    ]
    render_data_table(pd.DataFrame(runtime_rows, columns=["Runtime Field", "Value"]))
    st.markdown(
        f"{chip_html('FTMO-aware', 'ok')} {chip_html('Live state loaded', 'ok' if bot_state else 'warn')} {chip_html(mode, 'warn' if mode == 'DEMO' else 'ok')}",
        unsafe_allow_html=True,
    )
with right:
    render_surface(
        "Current Engine Behavior",
        "This panel is built from the recent log and local bot state, so it reflects what the engine has been doing.",
        points=recent_messages if recent_messages else ["No local bot log is available yet."],
        kicker="Recent Activity",
    )


def run() -> None:
    subprocess.run([sys.executable, "-m", "streamlit", "run", __file__], check=True)
