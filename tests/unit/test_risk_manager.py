"""Unit tests for risk_manager.py — FTMO buffers, position sizing, guardrails."""
from __future__ import annotations

import pytest

from risk_manager import (
    FTMOLimits,
    GuardrailDecision,
    build_ftmo_limits,
    calculate_position_size,
    calculate_spread_points,
    normalize_volume,
    safe_float,
    validate_ftmo_buffers,
    validate_spread,
    within_trading_window,
)
from datetime import datetime


# ── safe_float ───────────────────────────────────────────────

class TestSafeFloat:
    def test_valid_number(self):
        assert safe_float(3.14) == pytest.approx(3.14)

    def test_string_number(self):
        assert safe_float("2.5") == pytest.approx(2.5)

    def test_none_returns_default(self):
        assert safe_float(None) == 0.0

    def test_nan_returns_default(self):
        assert safe_float(float("nan")) == 0.0

    def test_inf_returns_default(self):
        assert safe_float(float("inf")) == 0.0

    def test_custom_default(self):
        assert safe_float(None, 99.9) == pytest.approx(99.9)


# ── build_ftmo_limits ────────────────────────────────────────

class TestBuildFTMOLimits:
    def test_min_allowed_equity(self):
        limits = build_ftmo_limits(160000, 8000, 16000)
        assert limits.min_allowed_equity == pytest.approx(144000.0)

    def test_fields_stored(self):
        limits = build_ftmo_limits(100000, 5000, 10000)
        assert limits.start_capital == 100000
        assert limits.max_daily_loss == 5000
        assert limits.max_total_loss == 10000


# ── validate_ftmo_buffers ────────────────────────────────────

class TestValidateFTMOBuffers:
    def setup_method(self):
        self.limits = build_ftmo_limits(160000, 8000, 16000)

    def test_healthy_state_allowed(self):
        decision = validate_ftmo_buffers(
            equity=160000, day_start_equity=160000,
            limits=self.limits, estimated_trade_risk=400,
            safety_daily_buffer=2000, safety_total_buffer=3000,
        )
        assert decision.allowed is True

    def test_daily_breach_blocked(self):
        # equity has dropped 7500 from day start — daily buffer exhausted
        decision = validate_ftmo_buffers(
            equity=152500, day_start_equity=160000,
            limits=self.limits, estimated_trade_risk=400,
            safety_daily_buffer=2000, safety_total_buffer=3000,
        )
        assert decision.allowed is False
        assert "daily" in decision.reason.lower()

    def test_total_breach_blocked(self):
        # equity near max total loss floor
        decision = validate_ftmo_buffers(
            equity=144500, day_start_equity=144500,
            limits=self.limits, estimated_trade_risk=400,
            safety_daily_buffer=2000, safety_total_buffer=3000,
        )
        assert decision.allowed is False
        assert "total" in decision.reason.lower()


# ── validate_spread ──────────────────────────────────────────

class TestValidateSpread:
    def test_ok_spread(self):
        assert validate_spread(200, 450).allowed is True

    def test_excessive_spread_blocked(self):
        decision = validate_spread(500, 450)
        assert decision.allowed is False
        assert "500" in decision.reason


# ── within_trading_window ────────────────────────────────────

class TestWithinTradingWindow:
    def test_inside_window(self):
        # Monday 10:00
        now = datetime(2026, 5, 11, 10, 0)
        assert within_trading_window(now, (0, 1, 2, 3, 4), 3, 17).allowed is True

    def test_outside_hours(self):
        now = datetime(2026, 5, 11, 22, 0)
        assert within_trading_window(now, (0, 1, 2, 3, 4), 3, 17).allowed is False

    def test_weekend_blocked(self):
        # Saturday
        now = datetime(2026, 5, 9, 10, 0)
        assert within_trading_window(now, (0, 1, 2, 3, 4), 3, 17).allowed is False


# ── normalize_volume ─────────────────────────────────────────

class TestNormalizeVolume:
    def test_basic_normalization(self):
        vol = normalize_volume(1.234, min_volume=0.01, volume_step=0.01, max_volume=100.0)
        assert vol == pytest.approx(1.23, abs=0.01)

    def test_below_min_returns_zero(self):
        assert normalize_volume(-1.0, 0.01, 0.01, 100.0) == 0.0

    def test_clamped_to_max(self):
        assert normalize_volume(200.0, 0.01, 0.01, 5.0) == pytest.approx(5.0)


# ── calculate_position_size ──────────────────────────────────

class TestCalculatePositionSize:
    class _FakeSymbolInfo:
        volume_min  = 0.01
        volume_step = 0.01
        volume_max  = 100.0

    def test_reasonable_size(self):
        size = calculate_position_size(
            equity=160000, risk_per_trade=0.0025,
            stop_distance=15.0, symbol_info=self._FakeSymbolInfo(),
        )
        assert size > 0
        assert size <= 100.0

    def test_zero_equity_returns_zero(self):
        assert calculate_position_size(0, 0.0025, 15, self._FakeSymbolInfo()) == 0.0
