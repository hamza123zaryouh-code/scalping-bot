"""XAUUSD V17 Live Dashboard endpoints — met sentiment, circuit breaker, sessie analytics."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException

from autonomous_xauusd.memory_layer import MemoryLayer
from autonomous_xauusd.settings import load_settings
from backend.api.deps import get_current_user
from backend.api.schemas.common import APIResponse
from core.session_engine import SessionEngine
from core.risk_engine import FTMOCompliance, FTMO_STARTING_CAPITAL, FTMO_DAILY_LOSS_LIMIT, FTMO_TOTAL_LOSS_LIMIT

logger = logging.getLogger(__name__)
router = APIRouter()

_STATE_PATH = Path("live_logs/bot_state.json")
_LOG_PATH = Path("live_logs/xauusd_live_bot.log")

_session_engine = SessionEngine()
_ftmo_compliance = FTMOCompliance()


def _load_bot_state() -> dict:
    if not _STATE_PATH.exists():
        return {}
    try:
        return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _get_memory() -> MemoryLayer:
    return MemoryLayer(load_settings().database_url)


@router.get("/live", response_model=APIResponse[dict], summary="Full live dashboard snapshot V17")
async def live_dashboard(_user: dict = Depends(get_current_user)):
    state = _load_bot_state()

    balance = state.get("balance", 0.0) or 0.0
    equity = state.get("equity", balance) or balance
    positions = state.get("open_positions", [])
    floating_pnl = sum(p.get("profit", 0.0) for p in positions)
    day_start_equity = state.get("day_start_equity", balance) or balance
    daily_pnl = round(equity - day_start_equity, 2)
    max_dd = state.get("max_drawdown_today", 0.0) or 0.0
    signals_today = state.get("signals_today", 0) or len(state.get("signal_history", []))
    mode = state.get("mode", "paper")

    try:
        memory = _get_memory()
        df = memory.trade_history(limit=5000)
        wins = int((df["pnl"] > 0).sum()) if not df.empty and "pnl" in df.columns else 0
        total = len(df)
        losses = total - wins
        win_rate = round(wins / total * 100, 1) if total > 0 else 0.0
        gross_profit = float(df.loc[df["pnl"] > 0, "pnl"].sum()) if not df.empty and "pnl" in df.columns else 0.0
        gross_loss = abs(float(df.loc[df["pnl"] < 0, "pnl"].sum())) if not df.empty and "pnl" in df.columns else 0.0
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0.0
        total_pnl = round(float(df["pnl"].sum()), 2) if not df.empty and "pnl" in df.columns else 0.0
        runtime_ai = memory.get_runtime_state("ai_confidence") or {}
        ai_confidence = float(runtime_ai.get("score", 0.0)) if isinstance(runtime_ai, dict) else 0.0

        # Signal type verdeling
        signal_type_dist = {}
        if not df.empty and "signal_type" in df.columns:
            signal_type_dist = df["signal_type"].value_counts().to_dict()

        # Recent performance (laatste 20 trades)
        recent_pnl = 0.0
        recent_wr = 0.0
        if not df.empty and len(df) >= 5:
            recent = df.tail(20)
            recent_pnl = float(recent["pnl"].sum())
            recent_wins = int((recent["pnl"] > 0).sum())
            recent_wr = round(recent_wins / len(recent) * 100, 1)

    except Exception:
        wins = losses = total = 0
        win_rate = profit_factor = total_pnl = ai_confidence = 0.0
        signal_type_dist = {}
        recent_pnl = recent_wr = 0.0

    # FTMO compliance
    starting_capital = FTMO_STARTING_CAPITAL
    ftmo = _ftmo_compliance.check(balance=equity, day_start=day_start_equity)

    drawdown_pct = round((starting_capital - equity) / starting_capital * 100, 2) if equity < starting_capital else 0.0
    daily_loss_used = abs(min(daily_pnl, 0.0))
    total_loss_used = abs(min(balance - starting_capital, 0.0))

    # Circuit breaker status uit bot_state
    circuit_breaker = state.get("circuit_breaker", {})
    if not isinstance(circuit_breaker, dict):
        circuit_breaker = {}

    # Sentiment data uit bot_state
    sentiment_data = state.get("last_sentiment", {})
    if not isinstance(sentiment_data, dict):
        sentiment_data = {}

    # Sessie informatie
    session_info = _session_engine.get_session_analytics()

    return APIResponse(data={
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "status": "live" if state else "offline",

        "account": {
            "balance": round(balance, 2),
            "equity": round(equity, 2),
            "floating_pnl": round(floating_pnl, 2),
            "daily_pnl": daily_pnl,
            "drawdown_pct": drawdown_pct,
            "drawdown_usd": round(max(starting_capital - equity, 0.0), 2),
        },

        "performance": {
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "total_pnl": total_pnl,
            "recent_pnl_20": round(recent_pnl, 2),
            "recent_win_rate_20": recent_wr,
            "signal_type_distribution": signal_type_dist,
        },

        "risk": {
            "daily_loss_limit": FTMO_DAILY_LOSS_LIMIT,
            "daily_loss_used": round(daily_loss_used, 2),
            "daily_loss_pct": round(daily_loss_used / FTMO_DAILY_LOSS_LIMIT * 100, 1) if FTMO_DAILY_LOSS_LIMIT else 0,
            "total_loss_limit": FTMO_TOTAL_LOSS_LIMIT,
            "total_loss_used": round(total_loss_used, 2),
            "total_loss_pct": round(total_loss_used / FTMO_TOTAL_LOSS_LIMIT * 100, 1) if FTMO_TOTAL_LOSS_LIMIT else 0,
            "can_trade": ftmo["can_trade"],
            "ftmo_status": ftmo["status"],
            "ftmo_warnings": ftmo["warnings"],
        },

        "circuit_breaker": {
            "active": circuit_breaker.get("circuit_breaker_active", False),
            "reason": circuit_breaker.get("circuit_breaker_reason", "none"),
            "can_trade": circuit_breaker.get("can_trade", True),
            "risk_multiplier": circuit_breaker.get("risk_multiplier", 1.0),
            "consecutive_losses": circuit_breaker.get("consecutive_losses", 0),
            "cooldown_until": circuit_breaker.get("cooldown_until"),
            "risk_level": circuit_breaker.get("risk_level", "NORMAAL"),
            "spread_ok": circuit_breaker.get("spread_ok", True),
            "volatility_ok": circuit_breaker.get("volatility_ok", True),
        },

        "sentiment": {
            "score": sentiment_data.get("score", 0.0),
            "label": sentiment_data.get("label", "neutral"),
            "confidence": sentiment_data.get("confidence", 0.0),
            "headline_count": sentiment_data.get("headline_count", 0),
            "rolling_avg": sentiment_data.get("rolling_avg", 0.0),
            "macro_event": sentiment_data.get("macro_event_detected", False),
            "macro_level": sentiment_data.get("macro_event_level", "LOW"),
            "risk_modifier": sentiment_data.get("risk_modifier", 1.0),
            "fetched_at": sentiment_data.get("fetched_at"),
        },

        "session": session_info,

        "activity": {
            "open_positions": len(positions),
            "signals_today": signals_today,
            "ai_confidence": round(ai_confidence, 2),
            "last_signal": state.get("last_signal_time"),
            "bot_cycles": state.get("cycle_count", 0),
            "engine_version": "V17",
        },
    })


@router.get("/equity-curve", summary="Equity curve data points")
async def equity_curve(_user: dict = Depends(get_current_user)):
    try:
        memory = _get_memory()
        df = memory.trade_history(limit=500)
        if df.empty:
            return APIResponse(data={"points": []})

        df = df.sort_values("opened_at") if "opened_at" in df.columns else df
        df["cumulative_pnl"] = df["pnl"].cumsum() if "pnl" in df.columns else 0

        starting = FTMO_STARTING_CAPITAL
        points = []
        for _, row in df.iterrows():
            ts = row.get("opened_at") or row.get("closed_at")
            if hasattr(ts, "isoformat"):
                ts = ts.isoformat()
            pnl_val = row.get("pnl", 0.0)
            cum_pnl = row.get("cumulative_pnl", 0.0)
            signal_type = row.get("signal_type", "UNKNOWN")
            market_regime = row.get("market_regime", "CHOPPY")
            points.append({
                "time": ts,
                "pnl": round(float(pnl_val) if pnl_val == pnl_val else 0.0, 2),
                "equity": round(starting + float(cum_pnl) if cum_pnl == cum_pnl else starting, 2),
                "cumulative_pnl": round(float(cum_pnl) if cum_pnl == cum_pnl else 0.0, 2),
                "signal_type": signal_type,
                "market_regime": market_regime,
            })

        return APIResponse(data={"points": points, "starting_capital": starting})
    except Exception as exc:
        logger.exception("Equity curve failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/monthly-pnl", summary="Monthly P&L breakdown")
async def monthly_pnl(_user: dict = Depends(get_current_user)):
    try:
        memory = _get_memory()
        df = memory.trade_history(limit=5000)
        if df.empty:
            return APIResponse(data={"months": []})

        df["month"] = pd.to_datetime(df["opened_at"]).dt.to_period("M").astype(str)
        by_month = df.groupby("month").agg(
            pnl=("pnl", "sum"),
            trades=("pnl", "count"),
            wins=("pnl", lambda x: (x > 0).sum()),
        ).reset_index()

        months = []
        for _, row in by_month.iterrows():
            total_trades = int(row["trades"])
            wins = int(row["wins"])
            pnl_val = round(float(row["pnl"]), 2)
            months.append({
                "month": row["month"],
                "pnl": pnl_val,
                "pnl_pct": round(pnl_val / FTMO_STARTING_CAPITAL * 100, 2),
                "trades": total_trades,
                "win_rate": round(wins / total_trades * 100, 1) if total_trades else 0,
                "target_met": pnl_val >= 8000,
            })

        return APIResponse(data={"months": months})
    except Exception as exc:
        logger.exception("Monthly PnL failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/drawdown-curve", summary="Drawdown curve over time")
async def drawdown_curve(_user: dict = Depends(get_current_user)):
    try:
        memory = _get_memory()
        df = memory.trade_history(limit=500)
        if df.empty:
            return APIResponse(data={"points": []})

        df = df.sort_values("opened_at") if "opened_at" in df.columns else df
        starting = FTMO_STARTING_CAPITAL
        cum_pnl = df["pnl"].cumsum() if "pnl" in df.columns else pd.Series([0.0] * len(df))
        equity_series = starting + cum_pnl
        peak = equity_series.cummax()
        dd_pct = ((equity_series - peak) / peak * 100).round(2)

        points = []
        for i, (_, row) in enumerate(df.iterrows()):
            ts = row.get("opened_at") or row.get("closed_at")
            if hasattr(ts, "isoformat"):
                ts = ts.isoformat()
            dd_val = float(dd_pct.iloc[i]) if i < len(dd_pct) else 0.0
            points.append({
                "time": ts,
                "drawdown_pct": dd_val if dd_val == dd_val else 0.0,
                "ftmo_limit": -6.0,
                "internal_limit": -4.0,
            })

        return APIResponse(data={"points": points})
    except Exception as exc:
        logger.exception("Drawdown curve failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/signal-heatmap", summary="Signal type performance heatmap")
async def signal_heatmap(_user: dict = Depends(get_current_user)):
    """Signal kwaliteitsanalyse per type en sessie."""
    try:
        memory = _get_memory()
        df = memory.trade_history(limit=5000)
        if df.empty:
            return APIResponse(data={"heatmap": []})

        if "signal_type" not in df.columns:
            return APIResponse(data={"heatmap": [], "note": "Geen signal_type data beschikbaar"})

        heatmap_data = []
        for sig_type, group in df.groupby("signal_type"):
            pnl = group["pnl"]
            wins = int((pnl > 0).sum())
            total = len(group)
            heatmap_data.append({
                "signal_type": sig_type,
                "total_trades": total,
                "wins": wins,
                "win_rate": round(wins / total * 100, 1) if total else 0,
                "total_pnl": round(float(pnl.sum()), 2),
                "avg_pnl": round(float(pnl.mean()), 2),
                "profit_factor": round(
                    float(pnl[pnl > 0].sum()) / float(pnl[pnl < 0].abs().sum()), 2
                ) if not pnl[pnl < 0].empty and pnl[pnl < 0].abs().sum() > 0 else 99.0,
            })

        heatmap_data.sort(key=lambda x: x["total_pnl"], reverse=True)
        return APIResponse(data={"heatmap": heatmap_data})
    except Exception as exc:
        logger.exception("Signal heatmap failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/session-analytics", summary="Trading session analytics")
async def session_analytics(_user: dict = Depends(get_current_user)):
    """Huidige sessie + analytics voor dashboard."""
    try:
        current = _session_engine.get_session_analytics()
        next_session = None
        if not current["is_valid_for_trading"]:
            next_dt = _session_engine.get_next_trading_session()
            next_session = next_dt.isoformat() if next_dt else None

        return APIResponse(data={
            "current_session": current,
            "next_valid_session": next_session,
        })
    except Exception as exc:
        logger.exception("Session analytics failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/ftmo-status", summary="FTMO compliance status")
async def ftmo_status(_user: dict = Depends(get_current_user)):
    """Volledige FTMO compliance check."""
    try:
        state = _load_bot_state()
        balance = state.get("balance", FTMO_STARTING_CAPITAL) or FTMO_STARTING_CAPITAL
        day_start = state.get("day_start_equity", FTMO_STARTING_CAPITAL) or FTMO_STARTING_CAPITAL

        compliance = _ftmo_compliance.check(balance=balance, day_start=day_start)
        return APIResponse(data=compliance)
    except Exception as exc:
        logger.exception("FTMO status failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/live-logs", summary="Recent live trading log entries")
async def live_logs(_user: dict = Depends(get_current_user), limit: int = 100):
    """Laatste log regels voor de live logs pagina."""
    try:
        if not _LOG_PATH.exists():
            return APIResponse(data={"logs": [], "note": "Geen log bestand gevonden"})

        lines = _LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
        recent = lines[-limit:]

        entries = []
        for line in recent:
            level = "INFO"
            if "ERROR" in line:    level = "ERROR"
            elif "WARNING" in line: level = "WARNING"
            elif "CRITICAL" in line: level = "CRITICAL"
            elif "DEBUG" in line:  level = "DEBUG"
            entries.append({"line": line, "level": level})

        return APIResponse(data={"logs": entries, "total_lines": len(lines)})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
