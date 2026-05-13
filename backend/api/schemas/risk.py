"""Risk-management schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field


class FTMOBufferStatus(BaseModel):
    daily_loss_used: float
    daily_loss_limit: float
    daily_remaining: float
    daily_buffer_pct: float
    total_loss_used: float
    total_loss_limit: float
    total_remaining: float
    total_buffer_pct: float
    daily_ok: bool
    total_ok: bool
    overall_ok: bool
    risk_level: str   # green | yellow | red


class RiskSnapshot(BaseModel):
    equity: float
    balance: float
    day_start_equity: float
    open_positions: int
    estimated_trade_risk: float
    ftmo_status: FTMOBufferStatus
    stress_score: float = Field(ge=0, le=100)
    fail_probability: float = Field(ge=0, le=1)
    exposure_usd: float
    spread_points: float
    session_active: bool
