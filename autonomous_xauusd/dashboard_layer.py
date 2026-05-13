from __future__ import annotations

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from .analytics_engine import compute_report
from .memory_layer import MemoryLayer
from .settings import load_settings


def render_dashboard() -> None:
    settings = load_settings()
    memory = MemoryLayer(settings.database_url)

    st.set_page_config(page_title="Autonomous XAUUSD Desk", layout="wide")
    st.title("Autonomous XAUUSD & Forex Desk")
    st.caption("Realtime monitoring - engine status, sentiment, analytics, ML feedback loop.")

    try:
        trades = memory.trade_history(limit=2000)
        models = memory.model_history()
        runtime = memory.get_runtime_state("engine_status") or {}
        sentiment_state = memory.get_runtime_state("last_sentiment") or {}
    except Exception as exc:
        st.error(
            "Autonomous database is not ready. Run `python -m autonomous_xauusd.init_db` "
            f"or start the backend/engine first. Details: {exc}"
        )
        return

    c1, c2, c3, c4, c5 = st.columns(5)
    realized_pnl = float(trades["pnl"].fillna(0.0).sum()) if not trades.empty else 0.0
    win_rate = float((trades["pnl"].fillna(0.0) > 0).mean()) if not trades.empty else 0.0
    latest_acc = float(models["accuracy"].iloc[-1]) if not models.empty else 0.0

    c1.metric("Mode", runtime.get("mode", settings.mode).upper())
    c2.metric("Open trades", str(runtime.get("open_positions", 0)))
    c3.metric("Realized PnL", f"{realized_pnl:+,.2f}")
    c4.metric("Win-rate", f"{win_rate:.1%}")
    c5.metric("ML accuracy", f"{latest_acc:.1%}")

    st.divider()

    st.subheader("Market sentiment")
    score = float(sentiment_state.get("score", 0.0))
    label = str(sentiment_state.get("label", "n/a"))
    headline_count = int(sentiment_state.get("headline_count", 0))
    fetched_at = sentiment_state.get("fetched_at", "-")
    color_map = {"bullish": "#2ecc71", "bearish": "#e74c3c", "neutral": "#95a5a6", "n/a": "#bdc3c7"}

    sentiment_col, sources_col = st.columns([1, 2])
    with sentiment_col:
        gauge = go.Figure(
            go.Indicator(
                mode="gauge+number",
                value=score,
                number={"font": {"size": 28}},
                title={"text": f"Sentiment: <b>{label.upper()}</b>", "font": {"size": 14}},
                gauge={
                    "axis": {"range": [-1, 1], "tickvals": [-1, -0.5, 0, 0.5, 1]},
                    "bar": {"color": color_map.get(label, "#bdc3c7")},
                    "steps": [
                        {"range": [-1, -0.25], "color": "#fadbd8"},
                        {"range": [-0.25, 0.25], "color": "#f9f9f9"},
                        {"range": [0.25, 1], "color": "#d5f5e3"},
                    ],
                    "threshold": {"line": {"color": "black", "width": 2}, "thickness": 0.75, "value": score},
                },
            )
        )
        gauge.update_layout(height=220, margin=dict(t=40, b=10, l=20, r=20))
        st.plotly_chart(gauge, use_container_width=True)
        st.caption(f"{headline_count} headlines analysed | updated: {str(fetched_at)[:19]}")

    with sources_col:
        sources = sentiment_state.get("sources", [])
        if sources:
            st.markdown("**Latest headlines:**")
            for source in sources:
                st.markdown(f"- {source}")
        else:
            st.info("No sentiment headlines available yet.")

    st.divider()

    if trades.empty:
        st.info("No trades logged yet. Start `xauusd-autonomous` to collect data.")
        return

    trades = trades.copy()
    trades["equity_curve"] = trades["pnl"].fillna(0.0).cumsum() + settings.paper_starting_balance

    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            px.line(trades, x="opened_at", y="equity_curve", title="Equity curve", markers=True),
            use_container_width=True,
        )
    with right:
        st.plotly_chart(
            px.scatter(
                trades,
                x="rsi_fast",
                y="pnl",
                color="side",
                size="h4_atr",
                hover_data=["opened_at", "market_regime", "signal_type", "sentiment_score"],
                title="RSI-5 vs PnL (size = H4 ATR)",
            ),
            use_container_width=True,
        )

    st.subheader("Analytics")
    report = compute_report(trades, models)

    a1, a2, a3, a4 = st.columns(4)
    a1.metric("Profit Factor", f"{report.profit_factor:.2f}")
    a2.metric("Avg. R:R", f"{report.avg_rr:.2f}")
    a3.metric("Max Drawdown", f"{report.max_drawdown:+,.2f}")
    a4.metric("Closed trades", str(report.closed_trades))

    tab_regime, tab_session, tab_side, tab_monthly = st.tabs(
        ["By regime", "By hour", "Long vs Short", "Monthly summary"]
    )

    with tab_regime:
        if report.by_regime:
            df_regime = _list_to_df(report.by_regime)
            st.plotly_chart(
                px.bar(df_regime, x="regime", y="pnl", color="win_rate", text="trades", title="PnL by regime"),
                use_container_width=True,
            )
            st.dataframe(df_regime, use_container_width=True)

    with tab_session:
        if report.by_session:
            df_session = _list_to_df(report.by_session)
            st.plotly_chart(
                px.bar(df_session, x="hour", y="pnl", color="win_rate", title="PnL by hour (UTC)"),
                use_container_width=True,
            )

    with tab_side:
        if report.by_side:
            df_side = _list_to_df(report.by_side)
            st.plotly_chart(
                px.bar(df_side, x="side", y="pnl", color="win_rate", title="Long vs Short"),
                use_container_width=True,
            )

    with tab_monthly:
        if report.monthly:
            df_monthly = _list_to_df(report.monthly)
            st.plotly_chart(
                px.bar(df_monthly, x="month", y="pnl", color="win_rate", title="Monthly PnL"),
                use_container_width=True,
            )
            st.dataframe(df_monthly, use_container_width=True)

    st.subheader("ML learning curve")
    learning_col, status_col = st.columns([1.5, 1])
    with learning_col:
        if not models.empty:
            st.plotly_chart(
                px.line(
                    models,
                    x="trained_at",
                    y=["accuracy", "precision", "recall", "f1_score"],
                    title="ML metrics over time",
                    markers=True,
                ),
                use_container_width=True,
            )
        else:
            st.info("No model training snapshots available yet.")

    with status_col:
        st.subheader("Runtime status")
        st.json(runtime or {"status": "not started"})

    st.subheader("Trade history")
    show_cols = [
        column
        for column in [
            "broker_ticket",
            "symbol",
            "side",
            "signal_type",
            "status",
            "opened_at",
            "closed_at",
            "entry_price",
            "exit_price",
            "pnl",
            "rsi_fast",
            "h4_adx",
            "market_regime",
            "sentiment_score",
        ]
        if column in trades.columns
    ]
    st.dataframe(trades[show_cols], use_container_width=True)


def _list_to_df(records: list[dict]):
    import pandas as pd

    return pd.DataFrame(records)


def main() -> None:
    render_dashboard()
