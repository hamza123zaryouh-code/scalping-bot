"""Live dashboard endpoints."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from autonomous_xauusd.memory_layer import MemoryLayer
from autonomous_xauusd.settings import load_settings
from backend.api.deps import get_current_user
from backend.api.schemas.common import APIResponse

logger = logging.getLogger(__name__)
router = APIRouter()

_STATE_PATH = Path("live_logs/bot_state.json")
_LOG_PATH = Path("live_logs/xauusd_live_bot.log")


def _load_bot_state() -> dict:
    if not _STATE_PATH.exists():
        return {}
    try:
        return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _get_memory() -> MemoryLayer:
    return MemoryLayer(load_settings().database_url)


@router.get("/live", response_model=APIResponse[dict], summary="Full live dashboard snapshot")
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
    except Exception:
        wins = losses = total = 0
        win_rate = profit_factor = total_pnl = ai_confidence = 0.0

    starting_capital = 160000.0
    drawdown_pct = round((starting_capital - equity) / starting_capital * 100, 2) if equity < starting_capital else 0.0
    daily_loss_limit = 8000.0
    total_loss_limit = 16000.0
    daily_loss_used = abs(min(daily_pnl, 0.0))
    total_loss_used = abs(min(balance - starting_capital, 0.0))

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
        },
        "risk": {
            "daily_loss_limit": daily_loss_limit,
            "daily_loss_used": round(daily_loss_used, 2),
            "daily_loss_pct": round(daily_loss_used / daily_loss_limit * 100, 1) if daily_loss_limit else 0,
            "total_loss_limit": total_loss_limit,
            "total_loss_used": round(total_loss_used, 2),
            "total_loss_pct": round(total_loss_used / total_loss_limit * 100, 1) if total_loss_limit else 0,
            "can_trade": daily_loss_used < daily_loss_limit and total_loss_used < total_loss_limit,
        },
        "activity": {
            "open_positions": len(positions),
            "signals_today": signals_today,
            "ai_confidence": round(ai_confidence, 2),
            "last_signal": state.get("last_signal_time"),
            "bot_cycles": state.get("cycle_count", 0),
        },
    })


@router.get("/equity-curve", summary="Equity curve data points")
async def equity_curve(_user: dict = Depends(get_current_user)):
    try:
        memory = _get_memory()
        df = memory.trade_history(limit=500)
        if df.empty:
            return APIResponse(data={"points": []})

        import pandas as pd
        df = df.sort_values("opened_at") if "opened_at" in df.columns else df
        df["cumulative_pnl"] = df["pnl"].cumsum() if "pnl" in df.columns else 0

        starting = 160000.0
        points = []
        for _, row in df.iterrows():
            ts = row.get("opened_at") or row.get("closed_at")
            if hasattr(ts, "isoformat"):
                ts = ts.isoformat()
            pnl_val = row.get("pnl", 0.0)
            cum_pnl = row.get("cumulative_pnl", 0.0)
            points.append({
                "time": ts,
                "pnl": round(float(pnl_val) if pnl_val == pnl_val else 0.0, 2),
                "equity": round(starting + float(cum_pnl) if cum_pnl == cum_pnl else starting, 2),
                "cumulative_pnl": round(float(cum_pnl) if cum_pnl == cum_pnl else 0.0, 2),
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

        import pandas as pd
        df["month"] = pd.to_datetime(df["opened_at"]).dt.to_period("M").astype(str)
        by_month = df.groupby("month").agg(
            pnl=("pnl", "sum"),
            trades=("pnl", "count"),
            wins=("pnl", lambda x: (x > 0).sum()),
        ).reset_index()

        months = []
        for _, row in by_month.iterrows():
            total = int(row["trades"])
            wins = int(row["wins"])
            months.append({
                "month": row["month"],
                "pnl": round(float(row["pnl"]), 2),
                "trades": total,
                "win_rate": round(wins / total * 100, 1) if total else 0,
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

        import pandas as pd
        import numpy as np

        df = df.sort_values("opened_at") if "opened_at" in df.columns else df
        starting = 160000.0
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
            points.append({"time": ts, "drawdown_pct": dd_val if dd_val == dd_val else 0.0})

        return APIResponse(data={"points": points})
    except Exception as exc:
        logger.exception("Drawdown curve failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
