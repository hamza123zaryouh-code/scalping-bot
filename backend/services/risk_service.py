"""Risk service for FTMO snapshots and simulation."""
from __future__ import annotations

import json
import logging
from contextlib import suppress
from pathlib import Path

from backend.api.schemas.risk import FTMOBufferStatus, RiskSnapshot
from backend.core.config import get_settings

logger = logging.getLogger(__name__)

STATE_PATH = Path("live_logs/bot_state.json")


class RiskService:
    def __init__(self) -> None:
        from core.risk_manager import build_ftmo_limits

        self._settings = get_settings()
        self._limits = build_ftmo_limits(
            start_capital=self._settings.starting_capital,
            max_daily_loss=self._settings.ftmo_max_daily_loss,
            max_total_loss=self._settings.ftmo_max_total_loss,
        )

    def compute_ftmo_buffers(
        self,
        equity: float,
        day_start_equity: float,
        estimated_trade_risk: float,
        safety_daily_buffer: float = 2000.0,
        safety_total_buffer: float = 3000.0,
    ) -> FTMOBufferStatus:
        limits = self._limits
        daily_loss_used = day_start_equity - equity
        total_loss_used = limits.start_capital - equity
        daily_remaining = limits.max_daily_loss - daily_loss_used
        total_remaining = limits.max_total_loss - total_loss_used

        daily_ok = daily_remaining > estimated_trade_risk + safety_daily_buffer
        total_ok = total_remaining > estimated_trade_risk + safety_total_buffer
        overall_ok = daily_ok and total_ok

        daily_buffer_pct = max(0.0, daily_remaining / limits.max_daily_loss * 100)
        total_buffer_pct = max(0.0, total_remaining / limits.max_total_loss * 100)

        if not overall_ok:
            risk_level = "red"
        elif daily_buffer_pct < 30 or total_buffer_pct < 30:
            risk_level = "yellow"
        else:
            risk_level = "green"

        return FTMOBufferStatus(
            daily_loss_used=round(daily_loss_used, 2),
            daily_loss_limit=limits.max_daily_loss,
            daily_remaining=round(daily_remaining, 2),
            daily_buffer_pct=round(daily_buffer_pct, 1),
            total_loss_used=round(total_loss_used, 2),
            total_loss_limit=limits.max_total_loss,
            total_remaining=round(total_remaining, 2),
            total_buffer_pct=round(total_buffer_pct, 1),
            daily_ok=daily_ok,
            total_ok=total_ok,
            overall_ok=overall_ok,
            risk_level=risk_level,
        )

    def _load_day_start_equity(self, fallback: float) -> float:
        if not STATE_PATH.exists():
            return fallback
        with suppress(Exception):
            state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            return float(state.get("day_start_equity", fallback))
        return fallback

    def _live_account_snapshot(self) -> tuple[float, float, int, float]:
        try:
            import MetaTrader5 as mt5  # type: ignore
        except ImportError:
            return self._settings.starting_capital, self._settings.starting_capital, 0, 0.0

        settings = self._settings
        if not settings.mt5_ready:
            return settings.starting_capital, settings.starting_capital, 0, 0.0

        initialized_here = False
        try:
            if mt5.account_info() is None:
                if not mt5.initialize():
                    logger.warning("MT5 initialize failed in risk snapshot: %s", mt5.last_error())
                    return settings.starting_capital, settings.starting_capital, 0, 0.0
                initialized_here = True
                if not mt5.login(settings.mt5_login, password=settings.mt5_password, server=settings.mt5_server):
                    logger.warning("MT5 login failed in risk snapshot: %s", mt5.last_error())
                    return settings.starting_capital, settings.starting_capital, 0, 0.0

            account_info = mt5.account_info()
            positions = mt5.positions_get() or []
            tick = mt5.symbol_info_tick("XAUUSD")
            spread_points = 0.0
            symbol_info = mt5.symbol_info("XAUUSD")
            if tick is not None and symbol_info is not None and float(symbol_info.point) > 0:
                spread_points = (float(tick.ask) - float(tick.bid)) / float(symbol_info.point)

            if account_info is None:
                return settings.starting_capital, settings.starting_capital, 0, spread_points

            return (
                float(account_info.equity),
                float(account_info.balance),
                len(positions),
                float(spread_points),
            )
        except Exception as exc:
            logger.warning("Live risk snapshot fallback triggered: %s", exc)
            return settings.starting_capital, settings.starting_capital, 0, 0.0
        finally:
            if initialized_here:
                with suppress(Exception):
                    mt5.shutdown()

    def get_snapshot(self) -> RiskSnapshot:
        settings = self._settings
        equity, balance, open_positions, spread_points = self._live_account_snapshot()
        estimated_trade_risk = settings.starting_capital * 0.0025
        day_start_equity = self._load_day_start_equity(balance)
        buffers = self.compute_ftmo_buffers(
            equity=equity,
            day_start_equity=day_start_equity,
            estimated_trade_risk=estimated_trade_risk,
        )
        consumed_pct = 100 - min(buffers.daily_buffer_pct, buffers.total_buffer_pct)
        stress_score = max(0.0, min(100.0, consumed_pct))
        fail_prob = stress_score / 200.0

        return RiskSnapshot(
            equity=equity,
            balance=balance,
            day_start_equity=day_start_equity,
            open_positions=open_positions,
            estimated_trade_risk=estimated_trade_risk,
            ftmo_status=buffers,
            stress_score=stress_score,
            fail_probability=round(fail_prob, 4),
            exposure_usd=0.0,
            spread_points=round(spread_points, 1),
            session_active=True,
        )
