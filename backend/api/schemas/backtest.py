"""Backtest request/response schemas."""
from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field, field_validator


class BacktestRequest(BaseModel):
    start_date: date = Field(..., examples=["2026-01-01"])
    end_date: date = Field(..., examples=["2026-05-11"])
    starting_capital: float = Field(160000.0, gt=0)
    risk_per_trade: float = Field(0.0025, gt=0, lt=0.1)
    sl_atr_multiplier: float = Field(1.5, gt=0)
    tp_atr_multiplier: float = Field(3.0, gt=0)
    max_open_trades: int = Field(3, ge=1, le=10)
    commission: float = Field(0.35, ge=0)
    spread_cost: float = Field(0.25, ge=0)
    symbol: str = Field("XAUUSD", pattern=r"^[A-Z]{3,10}$")

    @field_validator("end_date")
    @classmethod
    def end_after_start(cls, v: date, info: Any) -> date:
        if "start_date" in info.data and v <= info.data["start_date"]:
            raise ValueError("end_date must be after start_date")
        return v


class TradeRecord(BaseModel):
    side: str
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    stop_loss: float
    take_profit: float
    size: float
    pnl: float
    cumulative_equity: float


class BacktestMetrics(BaseModel):
    total_trades: int
    win_rate: float
    profit_factor: float
    sharpe_ratio: float
    max_drawdown_pct: float
    total_return_pct: float
    avg_win: float
    avg_loss: float
    expectancy: float
    calmar_ratio: float
    ftmo_passed: bool
    challenge_days: int


class BacktestResult(BaseModel):
    task_id: str
    metrics: BacktestMetrics
    trades: list[TradeRecord]
    equity_curve: list[dict]
    monthly_summary: list[dict]
    chart_path: str | None = None
