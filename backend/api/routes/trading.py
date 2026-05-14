"""Live trading data endpoints — positions, history, exposure."""
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


def _load_state() -> dict:
    if not _STATE_PATH.exists():
        return {}
    try:
        return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _get_memory() -> MemoryLayer:
    return MemoryLayer(load_settings().database_url)


@router.get("/positions", response_model=APIResponse[dict], summary="Open positions")
async def open_positions(_user: dict = Depends(get_current_user)):
    state = _load_state()
    positions = state.get("open_positions", [])
    equity = state.get("equity", 0.0)
    balance = state.get("balance", 0.0)
    floating_pnl = sum(p.get("profit", 0.0) for p in positions)

    return APIResponse(data={
        "positions": positions,
        "count": len(positions),
        "floating_pnl": round(floating_pnl, 2),
        "equity": equity,
        "balance": balance,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


@router.get("/history", response_model=APIResponse[dict], summary="Closed trade history")
async def trade_history(
    limit: int = 100,
    _user: dict = Depends(get_current_user),
):
    try:
        memory = _get_memory()
        df = memory.trade_history(limit=limit)
        if df.empty:
            return APIResponse(data={"trades": [], "total": 0})

        trades = df.to_dict(orient="records")
        for t in trades:
            for k, v in t.items():
                if hasattr(v, "isoformat"):
                    t[k] = v.isoformat()
                elif v != v:  # NaN
                    t[k] = None

        wins = sum(1 for t in trades if (t.get("pnl") or 0) > 0)
        losses = sum(1 for t in trades if (t.get("pnl") or 0) <= 0)
        total_pnl = sum((t.get("pnl") or 0) for t in trades)
        gross_profit = sum((t.get("pnl") or 0) for t in trades if (t.get("pnl") or 0) > 0)
        gross_loss = abs(sum((t.get("pnl") or 0) for t in trades if (t.get("pnl") or 0) < 0))
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0.0
        win_rate = round(wins / len(trades) * 100, 1) if trades else 0.0

        return APIResponse(data={
            "trades": trades,
            "total": len(trades),
            "wins": wins,
            "losses": losses,
            "total_pnl": round(total_pnl, 2),
            "profit_factor": profit_factor,
            "win_rate": win_rate,
        })
    except Exception as exc:
        logger.exception("Trade history failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/exposure", response_model=APIResponse[dict], summary="Risk exposure breakdown")
async def risk_exposure(_user: dict = Depends(get_current_user)):
    state = _load_state()
    positions = state.get("open_positions", [])
    balance = state.get("balance", 160000.0) or 160000.0
    equity = state.get("equity", balance)

    total_volume = sum(p.get("volume", 0.0) for p in positions)
    total_risk_usd = sum(abs(p.get("profit", 0.0)) for p in positions)
    exposure_pct = round(total_risk_usd / balance * 100, 2) if balance > 0 else 0.0
    drawdown_usd = round(balance - equity, 2) if equity < balance else 0.0
    drawdown_pct = round(drawdown_usd / balance * 100, 2) if balance > 0 else 0.0

    return APIResponse(data={
        "open_trades": len(positions),
        "total_volume": round(total_volume, 2),
        "total_risk_usd": round(total_risk_usd, 2),
        "exposure_pct": exposure_pct,
        "drawdown_usd": drawdown_usd,
        "drawdown_pct": drawdown_pct,
        "balance": balance,
        "equity": equity,
        "positions_detail": [
            {
                "ticket": p.get("ticket"),
                "symbol": p.get("symbol", "XAUUSD"),
                "side": p.get("type", "buy"),
                "volume": p.get("volume"),
                "entry": p.get("price_open"),
                "current": p.get("price_current"),
                "sl": p.get("sl"),
                "tp": p.get("tp"),
                "profit": p.get("profit"),
                "swap": p.get("swap", 0.0),
                "duration_min": _calc_duration(p.get("time")),
            }
            for p in positions
        ],
    })


def _calc_duration(open_time) -> int:
    if not open_time:
        return 0
    try:
        opened = datetime.fromtimestamp(int(open_time), tz=timezone.utc)
        delta = datetime.now(timezone.utc) - opened
        return int(delta.total_seconds() / 60)
    except Exception:
        return 0


@router.get("/signals/today", response_model=APIResponse[dict], summary="Today's signals")
async def signals_today(_user: dict = Depends(get_current_user)):
    state = _load_state()
    signals = state.get("signal_history", [])
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_signals = [s for s in signals if str(s.get("time", "")).startswith(today)]

    return APIResponse(data={
        "signals": today_signals,
        "count": len(today_signals),
        "buy_count": sum(1 for s in today_signals if s.get("side") == "buy"),
        "sell_count": sum(1 for s in today_signals if s.get("side") == "sell"),
    })
