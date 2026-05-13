from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return number


@dataclass(frozen=True)
class FTMOLimits:
    start_capital: float
    max_daily_loss: float
    max_total_loss: float
    min_allowed_equity: float


@dataclass(frozen=True)
class GuardrailDecision:
    allowed: bool
    reason: str


def build_ftmo_limits(start_capital: float, max_daily_loss: float, max_total_loss: float) -> FTMOLimits:
    start_capital = safe_float(start_capital, 160000.0)
    max_daily_loss = safe_float(max_daily_loss, 8000.0)
    max_total_loss = safe_float(max_total_loss, 16000.0)
    return FTMOLimits(
        start_capital=start_capital,
        max_daily_loss=max_daily_loss,
        max_total_loss=max_total_loss,
        min_allowed_equity=start_capital - max_total_loss,
    )


def is_demo_like_account(account_info: Any, allow_live_account: bool) -> GuardrailDecision:
    if allow_live_account:
        return GuardrailDecision(True, "Live account explicitly allowed by configuration")
    if account_info is None:
        return GuardrailDecision(False, "Account info unavailable")

    server = str(getattr(account_info, "server", "") or "").lower()
    company = str(getattr(account_info, "company", "") or "").lower()
    name = str(getattr(account_info, "name", "") or "").lower()
    combined = " ".join([server, company, name])
    if "demo" in combined:
        return GuardrailDecision(True, "Demo-like account detected")
    return GuardrailDecision(False, "Live account blocked because ALLOW_LIVE_ACCOUNT is false")


def within_trading_window(now: datetime, allowed_weekdays: tuple[int, ...], session_start_hour: int, session_end_hour: int) -> GuardrailDecision:
    if now.weekday() not in allowed_weekdays:
        return GuardrailDecision(False, f"Weekday {now.weekday()} not allowed")
    if not (session_start_hour <= now.hour < session_end_hour):
        return GuardrailDecision(False, f"Outside trading window {session_start_hour:02d}:00-{session_end_hour:02d}:00")
    return GuardrailDecision(True, "Within configured trading window")


def calculate_spread_points(tick: Any, symbol_info: Any) -> float:
    if tick is None or symbol_info is None:
        return float("inf")
    point = safe_float(getattr(symbol_info, "point", 0.0), 0.0)
    if point <= 0:
        return float("inf")
    ask = safe_float(getattr(tick, "ask", 0.0), 0.0)
    bid = safe_float(getattr(tick, "bid", 0.0), 0.0)
    if ask <= 0 or bid <= 0 or ask < bid:
        return float("inf")
    return (ask - bid) / point


def validate_spread(spread_points: float, max_spread_points: float) -> GuardrailDecision:
    if spread_points > max_spread_points:
        return GuardrailDecision(False, f"Spread too high: {spread_points:.1f} points > {max_spread_points:.1f}")
    return GuardrailDecision(True, f"Spread OK: {spread_points:.1f} points")


def validate_ftmo_buffers(
    equity: float,
    day_start_equity: float,
    limits: FTMOLimits,
    estimated_trade_risk: float,
    safety_daily_buffer: float,
    safety_total_buffer: float,
) -> GuardrailDecision:
    equity = safe_float(equity, limits.start_capital)
    day_start_equity = safe_float(day_start_equity, equity)
    estimated_trade_risk = safe_float(estimated_trade_risk)
    daily_floor = day_start_equity - limits.max_daily_loss
    remaining_daily = equity - daily_floor
    remaining_total = equity - limits.min_allowed_equity

    if remaining_daily <= estimated_trade_risk + safety_daily_buffer:
        return GuardrailDecision(False, "Insufficient FTMO daily buffer for next trade")
    if remaining_total <= estimated_trade_risk + safety_total_buffer:
        return GuardrailDecision(False, "Insufficient FTMO total buffer for next trade")
    return GuardrailDecision(True, "FTMO buffers sufficient")


def normalize_volume(raw_volume: float, min_volume: float, volume_step: float, max_volume: float) -> float:
    raw_volume = safe_float(raw_volume)
    min_volume = safe_float(min_volume, 0.01)
    volume_step = safe_float(volume_step, 0.01)
    max_volume = safe_float(max_volume, raw_volume if raw_volume > 0 else min_volume)

    if raw_volume <= 0:
        return 0.0
    steps = round((raw_volume - min_volume) / volume_step) if volume_step > 0 else 0
    normalized = min_volume + max(steps, 0) * volume_step
    normalized = max(normalized, min_volume)
    normalized = min(normalized, max_volume)
    return round(normalized, 2)


def calculate_position_size(equity: float, risk_per_trade: float, stop_distance: float, symbol_info: Any) -> float:
    equity = safe_float(equity)
    risk_per_trade = safe_float(risk_per_trade)
    stop_distance = safe_float(stop_distance)
    if equity <= 0 or risk_per_trade <= 0 or stop_distance <= 0:
        return 0.0

    risk_amount = equity * risk_per_trade
    raw_volume = risk_amount / stop_distance
    return normalize_volume(
        raw_volume=raw_volume,
        min_volume=safe_float(getattr(symbol_info, "volume_min", 0.01), 0.01),
        volume_step=safe_float(getattr(symbol_info, "volume_step", 0.01), 0.01),
        max_volume=safe_float(getattr(symbol_info, "volume_max", max(raw_volume, 0.01)), max(raw_volume, 0.01)),
    )
