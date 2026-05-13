from __future__ import annotations

import json
import os
from html import escape
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv
import requests
import streamlit as st

from config import load_live_bot_config


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_API_BASE = "http://localhost:8000/api/v1"
STATE_PATH = ROOT_DIR / "live_logs" / "bot_state.json"
LOG_PATH = ROOT_DIR / "live_logs" / "xauusd_live_bot.log"


def init_platform() -> None:
    load_dotenv(ROOT_DIR / ".env")
    st.session_state.setdefault("api_base", DEFAULT_API_BASE)
    st.session_state.setdefault("jwt_token", "")
    st.session_state.setdefault("auth_username", "admin")
    st.session_state.setdefault("auth_password", "changeme")
    st.session_state.setdefault("auto_refresh", False)


def current_mode() -> str:
    load_dotenv(ROOT_DIR / ".env")
    return (os.getenv("BOT_MODE", "demo") or "demo").strip().lower()


def api_base() -> str:
    return st.session_state.get("api_base", DEFAULT_API_BASE)


def auth_headers() -> dict[str, str]:
    token = st.session_state.get("jwt_token", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


def api_get(endpoint: str, params: dict[str, Any] | None = None, auth_required: bool = True) -> dict[str, Any] | None:
    try:
        response = requests.get(
            f"{api_base()}{endpoint}",
            headers=auth_headers() if auth_required else {},
            params=params,
            timeout=6,
        )
        if response.status_code == 401:
            return {"_auth_error": True}
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ConnectionError:
        return None
    except Exception:
        return None


def authenticate(username: str, password: str) -> tuple[bool, str]:
    try:
        response = requests.post(
            f"{api_base()}/auth/token",
            data={"username": username, "password": password},
            timeout=6,
        )
        if response.ok:
            payload = response.json()
            st.session_state["jwt_token"] = payload["access_token"]
            st.session_state["auth_username"] = username
            st.session_state["auth_password"] = password
            return True, "Secure session opened."
        return False, "Credentials were not accepted."
    except requests.exceptions.ConnectionError:
        return False, "Data service is offline."
    except Exception as exc:
        return False, str(exc)


def logout() -> None:
    st.session_state["jwt_token"] = ""


def inject_global_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            --desk-bg: #eef3f4;
            --desk-bg-soft: #e4ecee;
            --desk-panel: rgba(253, 255, 254, 0.96);
            --desk-panel-strong: #ffffff;
            --desk-sidebar: #152530;
            --desk-sidebar-soft: #1d3341;
            --desk-border: rgba(35, 78, 92, 0.14);
            --desk-border-strong: rgba(35, 78, 92, 0.24);
            --desk-text: #213743;
            --desk-text-strong: #10212b;
            --desk-text-soft: #5b6e79;
            --desk-text-muted: #748690;
            --desk-accent: #0f6d75;
            --desk-accent-soft: rgba(15, 109, 117, 0.10);
            --desk-success: #1d8b61;
            --desk-warn: #b97f2f;
            --desk-danger: #c55a67;
        }
        .stApp {
            background:
                linear-gradient(180deg, rgba(255,255,255,0.55) 0%, rgba(255,255,255,0.10) 100%),
                linear-gradient(135deg, var(--desk-bg) 0%, var(--desk-bg-soft) 100%);
            color: var(--desk-text);
            font-family: "Segoe UI", Aptos, sans-serif;
        }
        .stApp [data-testid="stHeader"] {
            background: transparent;
        }
        .block-container {
            padding-top: 1.8rem;
            padding-bottom: 2rem;
            max-width: 1400px;
        }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, var(--desk-sidebar) 0%, var(--desk-sidebar-soft) 100%);
            border-right: 1px solid rgba(255, 255, 255, 0.08);
        }
        .shell-brand {
            color: #f5fafc;
            font-size: 1.18rem;
            font-weight: 700;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            margin-bottom: 0.2rem;
        }
        .shell-subtitle {
            color: #c7d5dd;
            font-size: 0.82rem;
            line-height: 1.5;
            margin-bottom: 1rem;
        }
        .hero-wrap {
            background: linear-gradient(180deg, rgba(255,255,255,0.78), rgba(249,252,252,0.95));
            border: 1px solid var(--desk-border);
            border-radius: 24px;
            padding: 1.35rem 1.4rem;
            box-shadow: 0 20px 44px rgba(17, 33, 43, 0.08);
            margin-bottom: 1.25rem;
        }
        .hero-kicker {
            color: var(--desk-accent);
            font-size: 0.78rem;
            font-weight: 700;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            margin-bottom: 0.45rem;
        }
        .hero-title {
            color: var(--desk-text-strong);
            font-family: Georgia, "Times New Roman", serif;
            font-size: 2.05rem;
            line-height: 1.08;
            margin-bottom: 0.4rem;
        }
        .hero-copy {
            color: var(--desk-text-soft);
            font-size: 0.98rem;
            line-height: 1.65;
            max-width: 920px;
        }
        .panel-card,
        .desk-surface {
            background: linear-gradient(180deg, rgba(255,255,255,0.95), rgba(248,251,251,0.98));
            border: 1px solid var(--desk-border);
            border-radius: 20px;
            box-shadow: 0 16px 34px rgba(17, 33, 43, 0.06);
        }
        .panel-card {
            padding: 1rem 1rem 0.95rem 1rem;
            min-height: 126px;
        }
        .panel-label {
            color: var(--desk-text-muted);
            font-size: 0.78rem;
            font-weight: 700;
            letter-spacing: 0.1em;
            text-transform: uppercase;
            margin-bottom: 0.45rem;
        }
        .panel-value {
            color: var(--desk-text-strong);
            font-size: 1.55rem;
            font-weight: 700;
            line-height: 1.12;
            margin-bottom: 0.25rem;
        }
        .panel-note {
            color: var(--desk-text-soft);
            font-size: 0.88rem;
            line-height: 1.5;
        }
        .desk-surface {
            padding: 1.1rem 1.15rem;
        }
        .surface-kicker {
            color: var(--desk-accent);
            font-size: 0.74rem;
            font-weight: 700;
            letter-spacing: 0.1em;
            text-transform: uppercase;
            margin-bottom: 0.4rem;
        }
        .surface-title {
            color: var(--desk-text-strong);
            font-family: Georgia, "Times New Roman", serif;
            font-size: 1.15rem;
            margin-bottom: 0.4rem;
        }
        .surface-copy {
            color: var(--desk-text-soft);
            font-size: 0.93rem;
            line-height: 1.62;
        }
        .surface-list {
            margin: 0.7rem 0 0 0;
            padding-left: 1rem;
            color: var(--desk-text);
        }
        .surface-list li {
            margin-bottom: 0.35rem;
            line-height: 1.5;
        }
        .status-chip {
            display: inline-block;
            padding: 0.3rem 0.7rem;
            border-radius: 999px;
            font-size: 0.76rem;
            font-weight: 700;
            letter-spacing: 0.04em;
            border: 1px solid transparent;
        }
        .status-chip.ok {
            color: #126749;
            background: rgba(29, 139, 97, 0.14);
            border-color: rgba(29, 139, 97, 0.24);
        }
        .status-chip.warn {
            color: #8f611f;
            background: rgba(185, 127, 47, 0.15);
            border-color: rgba(185, 127, 47, 0.24);
        }
        .status-chip.bad {
            color: #95424d;
            background: rgba(197, 90, 103, 0.14);
            border-color: rgba(197, 90, 103, 0.22);
        }
        .empty-panel {
            border: 1px dashed var(--desk-border-strong);
            border-radius: 20px;
            padding: 1.05rem 1rem;
            background: rgba(250, 252, 252, 0.9);
            color: var(--desk-text-soft);
        }
        .stButton > button,
        .stFormSubmitButton > button {
            background: linear-gradient(180deg, #16757c 0%, #0f6268 100%);
            color: #f7fbfc;
            border: none;
            border-radius: 12px;
            font-weight: 700;
            box-shadow: 0 10px 20px rgba(15, 98, 104, 0.18);
        }
        .stButton > button:hover,
        .stFormSubmitButton > button:hover {
            background: linear-gradient(180deg, #1a8188 0%, #117076 100%);
        }
        .stCheckbox > label,
        .stTextInput label,
        .stNumberInput label,
        .stSelectbox label,
        .stMarkdown,
        .stMarkdown p,
        .stMarkdown li,
        .stCaption,
        label {
            color: var(--desk-text) !important;
        }
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] .stCaption,
        [data-testid="stSidebar"] .stMarkdown,
        [data-testid="stSidebar"] .stMarkdown p,
        [data-testid="stSidebar"] .stMarkdown li,
        [data-testid="stSidebar"] p,
        [data-testid="stSidebar"] span,
        [data-testid="stSidebar"] small,
        [data-testid="stSidebar"] strong {
            color: #e8f0f3 !important;
        }
        [data-testid="stSidebar"] div[data-baseweb="input"] > div,
        [data-testid="stSidebar"] div[data-baseweb="base-input"] > div {
            background: rgba(255, 255, 255, 0.10);
            border: 1px solid rgba(255, 255, 255, 0.16);
        }
        [data-testid="stSidebar"] div[data-baseweb="input"] input,
        [data-testid="stSidebar"] div[data-baseweb="base-input"] input {
            color: #f5fafc;
            -webkit-text-fill-color: #f5fafc;
        }
        [data-testid="stSidebar"] div[data-testid="stNumberInputContainer"] button,
        [data-testid="stSidebar"] svg {
            color: #d8e5ea;
            fill: #d8e5ea;
        }
        [data-testid="stSidebar"] .stCheckbox label[data-baseweb="checkbox"] + div,
        [data-testid="stSidebar"] .stCheckbox label[data-baseweb="checkbox"] {
            color: #e8f0f3 !important;
        }
        div[data-baseweb="input"] > div,
        div[data-baseweb="base-input"] > div {
            background: rgba(255,255,255,0.96);
            border: 1px solid var(--desk-border);
            border-radius: 12px;
        }
        div[data-baseweb="input"] input,
        div[data-baseweb="base-input"] input {
            color: var(--desk-text-strong);
        }
        div[data-testid="stNumberInputContainer"] button {
            color: var(--desk-accent);
        }
        [data-testid="stDataFrame"] {
            background: rgba(255,255,255,0.94);
            border: 1px solid var(--desk-border);
            border-radius: 16px;
            overflow: hidden;
        }
        [data-testid="stDataFrameResizable"] {
            border-radius: 16px;
        }
        [data-testid="stDataFrame"] [role="grid"] {
            color: var(--desk-text-strong);
        }
        [data-testid="stElementToolbar"] {
            background: transparent;
        }
        .stPlotlyChart {
            background: linear-gradient(180deg, rgba(255,255,255,0.95), rgba(248,251,251,0.98));
            border: 1px solid var(--desk-border);
            border-radius: 20px;
            padding: 0.35rem 0.35rem 0.1rem 0.35rem;
            box-shadow: 0 16px 34px rgba(17, 33, 43, 0.06);
        }
        h1, h2, h3, h4, h5, h6 {
            color: var(--desk-text-strong);
            font-family: Georgia, "Times New Roman", serif;
        }
        .desk-divider {
            height: 1px;
            background: linear-gradient(90deg, transparent 0%, rgba(35,78,92,0.18) 18%, rgba(35,78,92,0.18) 82%, transparent 100%);
            margin: 1rem 0 1.1rem 0;
        }
        @media (max-width: 900px) {
            .hero-title {
                font-size: 1.6rem;
            }
            .block-container {
                padding-top: 1.2rem;
            }
            .panel-card {
                min-height: auto;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar(page_label: str) -> None:
    mode = current_mode().upper()
    service_health = api_get("/health", auth_required=False)
    service_ok = bool(service_health and service_health.get("status") == "healthy")

    with st.sidebar:
        st.markdown('<div class="shell-brand">XAUUSD Expert Desk</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="shell-subtitle">Live supervision, review discipline and FTMO risk control for the active trading workspace.</div>',
            unsafe_allow_html=True,
        )
        tone = "ok" if st.session_state.get("jwt_token") else "warn"
        session_label = "Authenticated" if st.session_state.get("jwt_token") else "Restricted"
        st.markdown(
            f'<span class="status-chip {tone}">{page_label} | {session_label}</span>',
            unsafe_allow_html=True,
        )
        st.caption(f"Execution mode: {mode}")
        st.caption("Data service: online" if service_ok else "Data service: offline")
        st.markdown('<div class="desk-divider"></div>', unsafe_allow_html=True)
        st.markdown("**Secure Access**")
        username = st.text_input("Username", key="auth_username")
        password = st.text_input("Password", type="password", key="auth_password")
        login_col, logout_col = st.columns(2)
        if login_col.button("Open Session", use_container_width=True):
            ok, message = authenticate(username, password)
            if ok:
                st.success(message)
                st.rerun()
            else:
                st.error(message)
        if logout_col.button("Clear", use_container_width=True):
            logout()
            st.rerun()
        st.markdown('<div class="desk-divider"></div>', unsafe_allow_html=True)
        st.checkbox("Auto-refresh", key="auto_refresh", help="Refresh the page periodically while monitoring.")
        st.caption("This interface stays local-first. Protected endpoints require an active session.")


def require_session() -> None:
    if not st.session_state.get("jwt_token"):
        render_empty_panel(
            "Secure session required",
            "Open the sidebar and authenticate before loading live trading data.",
        )
        st.stop()


def render_page_header(kicker: str, title: str, copy: str) -> None:
    st.markdown(
        f"""
        <div class="hero-wrap">
            <div class="hero-kicker">{escape(kicker)}</div>
            <div class="hero-title">{escape(title)}</div>
            <div class="hero-copy">{escape(copy)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metric_card(label: str, value: str, note: str) -> None:
    st.markdown(
        f"""
        <div class="panel-card">
            <div class="panel-label">{escape(label)}</div>
            <div class="panel-value">{escape(value)}</div>
            <div class="panel-note">{escape(note)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_surface(title: str, copy: str, points: Iterable[str] | None = None, kicker: str | None = None) -> None:
    list_html = ""
    if points:
        items = "".join(f"<li>{escape(point)}</li>" for point in points)
        list_html = f'<ul class="surface-list">{items}</ul>'
    kicker_html = f'<div class="surface-kicker">{escape(kicker)}</div>' if kicker else ""
    st.markdown(
        f"""
        <div class="desk-surface">
            {kicker_html}
            <div class="surface-title">{escape(title)}</div>
            <div class="surface-copy">{escape(copy)}</div>
            {list_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_data_table(data: Any) -> None:
    if hasattr(data, "style"):
        styled = (
            data.style
            .set_properties(
                **{
                    "background-color": "#fbfdfd",
                    "color": "#10212b",
                    "border-color": "rgba(35, 78, 92, 0.10)",
                }
            )
            .set_table_styles(
                [
                    {
                        "selector": "th",
                        "props": [
                            ("background-color", "#e2ecee"),
                            ("color", "#10212b"),
                            ("font-weight", "700"),
                            ("border-bottom", "1px solid rgba(35, 78, 92, 0.16)"),
                        ],
                    },
                    {
                        "selector": "td",
                        "props": [
                            ("border-bottom", "1px solid rgba(35, 78, 92, 0.07)"),
                        ],
                    },
                ],
                overwrite=False,
            )
        )
        st.dataframe(styled, use_container_width=True, hide_index=True)
        return
    st.dataframe(data, use_container_width=True, hide_index=True)


def load_bot_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_recent_bot_messages(limit: int = 6) -> list[str]:
    if not LOG_PATH.exists():
        return []
    try:
        lines = LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    recent = [line.strip() for line in lines if line.strip()]
    return recent[-limit:]


def load_bot_analysis() -> dict[str, Any]:
    config = load_live_bot_config(ROOT_DIR)
    state = load_bot_state()
    recent_messages = load_recent_bot_messages()
    weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    allowed_days = ", ".join(
        weekdays[index] for index in config.allowed_weekdays if 0 <= index < len(weekdays)
    ) or "Not set"
    last_event = recent_messages[-1] if recent_messages else "No recent bot log available."

    last_signal = "None"
    if state.get("last_trade_time"):
        if state.get("last_long_signal_time") == state.get("last_trade_time"):
            last_signal = f"LONG at {state['last_trade_time']}"
        elif state.get("last_short_signal_time") == state.get("last_trade_time"):
            last_signal = f"SHORT at {state['last_trade_time']}"
        else:
            last_signal = str(state.get("last_trade_time"))

    return {
        "symbol": config.symbol,
        "timeframe": config.timeframe,
        "mode": config.bot_mode.upper(),
        "check_interval_seconds": config.check_interval_seconds,
        "history_bars": config.history_bars,
        "risk_per_trade_pct": config.risk_per_trade * 100,
        "sl_atr": config.stop_loss_atr_multiplier,
        "tp_atr": config.take_profit_atr_multiplier,
        "max_open_positions": config.max_open_positions,
        "max_spread_points": config.max_spread_points,
        "daily_limit": config.max_daily_loss_limit,
        "total_limit": config.max_total_loss_limit,
        "daily_buffer": config.safety_daily_buffer,
        "total_buffer": config.safety_total_buffer,
        "trading_window": f"{config.session_start_hour:02d}:00 to {config.session_end_hour:02d}:00",
        "allowed_days": allowed_days,
        "cooldown_minutes": config.duplicate_signal_cooldown_minutes,
        "volume_multiplier": config.min_volume_multiplier,
        "telegram_ready": config.telegram_ready,
        "heartbeat_minutes": config.status_heartbeat_minutes,
        "order_comment": config.order_comment,
        "day_start_equity": state.get("day_start_equity"),
        "last_processed_bar": state.get("last_processed_bar"),
        "last_trade_time": state.get("last_trade_time"),
        "last_heartbeat_time": state.get("last_heartbeat_time"),
        "last_signal": last_signal,
        "telegram_messages_sent": state.get("telegram_messages_sent", 0),
        "current_trading_day": state.get("current_trading_day"),
        "recent_messages": recent_messages,
        "last_event": last_event,
    }


def render_empty_panel(title: str, copy: str) -> None:
    st.markdown(
        f'<div class="empty-panel"><strong>{escape(title)}</strong><br/>{escape(copy)}</div>',
        unsafe_allow_html=True,
    )


def chip_html(text: str, tone: str = "ok") -> str:
    safe_tone = tone if tone in {"ok", "warn", "bad"} else "ok"
    return f'<span class="status-chip {safe_tone}">{escape(text)}</span>'


def format_money(value: Any) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        amount = 0.0
    sign = "-" if amount < 0 else ""
    return f"{sign}$ {abs(amount):,.2f}"


def format_pct(value: Any, assume_fraction: bool = True) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    if assume_fraction and abs(number) <= 1:
        number *= 100.0
    return f"{number:.1f}%"


def apply_plotly_theme(fig: Any) -> None:
    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#fbfdfd",
        font={"color": "#213743", "family": "Segoe UI"},
        colorway=["#0f6d75", "#1d8b61", "#b97f2f", "#c55a67"],
        margin=dict(l=12, r=12, t=28, b=12),
    )
    fig.update_xaxes(showgrid=False, zeroline=False)
    fig.update_yaxes(gridcolor="rgba(35, 78, 92, 0.10)", zeroline=False)
