"""Trade analytics page for the expert desk."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from components.platform import (
    api_get,
    apply_plotly_theme,
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


st.set_page_config(page_title="Trade Analytics | XAUUSD", layout="wide")
init_platform()
inject_global_styles()
render_sidebar("Trade Analytics")

render_page_header(
    kicker="Performance Review",
    title="Trade Analytics",
    copy=(
        "A rebuilt review page for realized P and L, trade count and monthly performance quality. "
        "The layout stays useful even while your trade history is still developing."
    ),
)

require_session()

payload = api_get("/analytics/metrics")
if payload is None:
    render_empty_panel("Data service unavailable", "Analytics could not be loaded from the local trading service.")
    st.stop()

if payload.get("_auth_error"):
    render_empty_panel("Session expired", "Re-authenticate from the sidebar to continue reviewing analytics.")
    st.stop()

data = payload.get("data", {})
monthly = pd.DataFrame(data.get("monthly_summary", []))
analytics = pd.DataFrame(data.get("trade_analytics", []))

if monthly.empty and analytics.empty:
    placeholder_cols = st.columns(3)
    placeholder_cards = [
        ("Recorded Trades", "0", "No closed trades have been written into the analytics store yet."),
        ("Monthly Review", "Pending", "Monthly summaries will appear after the first completed trade cycle."),
        ("Desk State", "Ready", "The review page is connected and waiting for realized trade data."),
    ]
    for col, card in zip(placeholder_cols, placeholder_cards):
        with col:
            render_metric_card(*card)

    st.markdown("### Review Structure")
    structure_cols = st.columns(2, gap="large")
    with structure_cols[0]:
        render_surface(
            "What Will Appear Here",
            "Once trades close, this page will expand into a review desk rather than a blank screen.",
            points=[
                "Monthly performance summaries.",
                "Closed-trade diagnostics.",
                "Win-rate and expectancy review.",
            ],
            kicker="Future Data",
        )
    with structure_cols[1]:
        render_surface(
            "Why The Empty State Is Kept Clean",
            "During early demo activity, the page should stay credible and readable instead of looking broken.",
            points=[
                "No fake charts are shown.",
                "No decorative filler replaces real data.",
                "The page remains ready for the first closed trade set.",
            ],
            kicker="Design Rule",
        )
    st.stop()

total_pnl = float(monthly["pnl"].sum()) if not monthly.empty and "pnl" in monthly.columns else 0.0
winning_months = int((monthly["pnl"] > 0).sum()) if not monthly.empty and "pnl" in monthly.columns else 0
avg_win_rate = monthly["win_rate"].mean() if not monthly.empty and "win_rate" in monthly.columns else 0.0
trade_count = int(monthly["trades"].sum()) if not monthly.empty and "trades" in monthly.columns else len(analytics)

summary_cols = st.columns(4)
summary_cards = [
    ("Total P and L", format_money(total_pnl), "Aggregated realized performance."),
    ("Winning Months", str(winning_months), "Number of positive months on record."),
    ("Average Win Rate", format_pct(avg_win_rate), "Normalized for either fraction or percent inputs."),
    ("Recorded Trades", str(trade_count), "Closed trades available for review."),
]
for col, card in zip(summary_cols, summary_cards):
    with col:
        render_metric_card(*card)

if not monthly.empty and "pnl" in monthly.columns:
    st.markdown("### Monthly Net Performance")
    monthly_chart = monthly.copy()
    monthly_chart["Outcome"] = monthly_chart["pnl"].apply(lambda value: "Profit" if float(value) >= 0 else "Loss")
    fig = px.bar(
        monthly_chart,
        x="month",
        y="pnl",
        color="Outcome",
        color_discrete_map={"Profit": "#1d8b61", "Loss": "#c55a67"},
        labels={"month": "Month", "pnl": "Net P and L"},
    )
    apply_plotly_theme(fig)
    fig.update_layout(legend_title_text="")
    st.plotly_chart(fig, use_container_width=True)

    monthly_table = monthly.copy()
    for column in monthly_table.columns:
        if column == "month":
            continue
        lowered = column.lower()
        if "pnl" in lowered or "trade" in lowered:
            if "trade" in lowered:
                monthly_table[column] = monthly_table[column].map(lambda value: int(float(value)))
            else:
                monthly_table[column] = monthly_table[column].map(format_money)
        elif "rate" in lowered or "pct" in lowered:
            monthly_table[column] = monthly_table[column].map(format_pct)
    render_data_table(monthly_table)

analytics_left, analytics_right = st.columns([1.15, 0.85], gap="large")

with analytics_left:
    if not analytics.empty:
        st.markdown("### Detailed Trade Review")
        analytics_table = analytics.copy()
        for column in analytics_table.columns:
            lowered = column.lower()
            if "pnl" in lowered or "expectancy" in lowered:
                analytics_table[column] = analytics_table[column].map(format_money)
            elif "rate" in lowered or "pct" in lowered:
                analytics_table[column] = analytics_table[column].map(format_pct)
        render_data_table(analytics_table)

with analytics_right:
    review_points = [
        "Use monthly trend before judging single trades.",
        "Look for consistency, not only gross P and L.",
        "Review expectancy and win rate together.",
    ]
    if not monthly.empty and "pnl" in monthly.columns and float(total_pnl) < 0:
        review_points.insert(0, "Current aggregate performance is negative and needs closer review.")
    render_surface(
        "Review Discipline",
        "This panel keeps the page anchored in evaluation rather than decoration.",
        points=review_points,
        kicker="Operator Notes",
    )
