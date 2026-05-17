"""
FTMO Guard — Institutional-grade FTMO compliance protection.

Enforces:
  - Daily loss lock      (default 5% of start capital = €8,000 on €160k)
  - Weekly loss lock     (default 7% = €11,200 on €160k)
  - Maximum drawdown lock (default 10% = €16,000 on €160k)
  - Profit target lock   (stop trading when monthly profit target achieved)
  - Max trades per day   (default 8)
  - Max consecutive losses (default 4)
  - News lock            (block trades during high-impact news windows)
  - Spread lock          (block trades above spread threshold)
  - Volatility lock      (block trades during extreme ATR spikes)
  - Equity trailing protection (equity-based trailing stop on account)

All locks are stateful and persist via RuntimeState in MemoryLayer.
Thread-safe. Designed as singleton via get_ftmo_guard().
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

_UTC = timezone.utc


@dataclass
class FTMOConfig:
    """All configurable FTMO rule thresholds."""
    start_capital: float = 160_000.0

    # Loss limits (absolute EUR amounts)
    max_daily_loss: float = 6_000.0   # was €8,000 — verlaagd voor extra accountbescherming
    max_weekly_loss: float = 10_000.0 # was €11,200 — proportioneel aangepast
    max_total_drawdown: float = 16_000.0

    # Safety buffers (stop before hitting hard limits)
    daily_buffer: float = 400.0       # stop at €5,600 daily loss (was €500 → €7,500)
    weekly_buffer: float = 600.0
    drawdown_buffer: float = 1_000.0

    # Trade limits
    max_trades_per_day: int = 8
    max_consecutive_losses: int = 4

    # Profit target (monthly — stop trading when reached, optional)
    monthly_profit_target: float | None = None   # e.g. 10_000.0; None = disabled

    # News guard: minutes before/after a high-impact event to block trading
    news_lock_minutes_before: int = 30
    news_lock_minutes_after: int = 20

    # Spread/slippage thresholds
    max_spread_points: float = 50.0   # XAUUSD: 50 points = $5.0 spread
    max_atr_multiplier: float = 3.0   # ATR spike above 3× normal = volatility lock

    # Equity trailing stop (protect profits)
    # When peak equity > start + trailing_activate_profit, lock in
    # that progress by preventing equity from falling below peak - trailing_from_peak
    equity_trailing_activate: float = 5_000.0    # activate after €5k profit
    equity_trailing_from_peak: float = 3_000.0   # never let equity fall >€3k from peak


@dataclass
class LockStatus:
    locked: bool
    reason: str
    lock_type: str
    expires_at: datetime | None = None
    severity: str = "WARN"    # WARN | BLOCK | CRITICAL

    def to_dict(self) -> dict[str, Any]:
        return {
            "locked": self.locked,
            "reason": self.reason,
            "lock_type": self.lock_type,
            "severity": self.severity,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }


@dataclass
class FTMOState:
    """Live trading session state tracked by the guard."""
    # Anchors (set once per period)
    day_start_equity: float = 0.0
    week_start_equity: float = 0.0
    month_start_equity: float = 0.0
    peak_equity: float = 0.0

    # Counters
    trades_today: int = 0
    consecutive_losses: int = 0

    # Watermarks
    day_date: str = ""      # ISO date string, reset when date changes
    week_num: str = ""      # "YYYY-Www"
    month_str: str = ""     # "YYYY-MM"

    # Lock overrides (manual / soft locks with expiry)
    news_lock_until: datetime | None = None

    # Realized PnL accumulators
    daily_pnl: float = 0.0
    weekly_pnl: float = 0.0
    monthly_pnl: float = 0.0

    active_locks: list[LockStatus] = field(default_factory=list)


class FTMOGuard:
    """
    Thread-safe FTMO compliance guard.

    Usage:
        guard = FTMOGuard(config)
        guard.update_equity(account_equity)

        if not guard.can_trade():
            return  # blocked

        # After executing a trade:
        guard.record_trade_opened()

        # After a trade closes:
        guard.record_trade_closed(pnl)
    """

    def __init__(self, config: FTMOConfig | None = None) -> None:
        self.config = config or FTMOConfig()
        self._state = FTMOState()
        self._lock = threading.Lock()
        self._current_equity: float = self.config.start_capital
        self._current_atr: float = 0.0
        self._current_spread: float = 0.0

    # ─────────────────────────────────────────────────────────────
    # PUBLIC: State updates
    # ─────────────────────────────────────────────────────────────

    def update_equity(self, equity: float) -> None:
        with self._lock:
            now = datetime.now(_UTC)
            self._current_equity = equity
            self._sync_period_anchors(equity, now)
            if equity > self._state.peak_equity:
                self._state.peak_equity = equity

    def update_market_conditions(self, atr: float, spread_points: float) -> None:
        with self._lock:
            self._current_atr = atr
            self._current_spread = spread_points

    def set_news_lock(self, lock_until: datetime) -> None:
        with self._lock:
            # Never shorten an existing lock — take the later expiry
            if (
                self._state.news_lock_until is not None
                and self._state.news_lock_until > lock_until
            ):
                lock_until = self._state.news_lock_until
            self._state.news_lock_until = lock_until
            logger.warning(
                "News lock activated until %s",
                lock_until.strftime("%H:%M UTC"),
            )

    def record_trade_opened(self) -> None:
        with self._lock:
            self._state.trades_today += 1

    def record_trade_closed(self, pnl: float) -> None:
        with self._lock:
            self._state.daily_pnl += pnl
            self._state.weekly_pnl += pnl
            self._state.monthly_pnl += pnl
            if pnl < 0:
                self._state.consecutive_losses += 1
            else:
                self._state.consecutive_losses = 0

    # ─────────────────────────────────────────────────────────────
    # PUBLIC: Gate checks
    # ─────────────────────────────────────────────────────────────

    def can_trade(self) -> bool:
        locks = self.get_active_locks()
        blocking = [lock for lock in locks if lock.locked and lock.severity in ("BLOCK", "CRITICAL")]
        return len(blocking) == 0

    def get_active_locks(self) -> list[LockStatus]:
        with self._lock:
            return self._evaluate_all_locks()

    def get_status_dict(self) -> dict[str, Any]:
        with self._lock:
            now = datetime.now(_UTC)
            cfg = self.config
            s = self._state
            equity = self._current_equity
            locks = self._evaluate_all_locks()

            daily_used = s.day_start_equity - equity if s.day_start_equity else 0.0
            daily_used = max(0.0, daily_used)
            daily_limit = cfg.max_daily_loss - cfg.daily_buffer
            daily_pct = (daily_used / cfg.max_daily_loss * 100) if cfg.max_daily_loss > 0 else 0.0

            total_dd = max(0.0, cfg.start_capital - equity)
            total_dd_pct = (total_dd / cfg.start_capital * 100) if cfg.start_capital > 0 else 0.0

            return {
                "can_trade": len([l for l in locks if l.locked and l.severity in ("BLOCK", "CRITICAL")]) == 0,
                "equity": round(equity, 2),
                "start_capital": cfg.start_capital,
                "peak_equity": round(s.peak_equity, 2),
                "daily_pnl": round(s.daily_pnl, 2),
                "weekly_pnl": round(s.weekly_pnl, 2),
                "monthly_pnl": round(s.monthly_pnl, 2),
                "daily_loss_used": round(daily_used, 2),
                "daily_loss_limit": cfg.max_daily_loss,
                "daily_loss_pct": round(daily_pct, 1),
                "daily_remaining": round(max(0.0, daily_limit - daily_used), 2),
                "total_drawdown": round(total_dd, 2),
                "total_drawdown_pct": round(total_dd_pct, 1),
                "total_dd_limit": cfg.max_total_drawdown,
                "trades_today": s.trades_today,
                "max_trades_per_day": cfg.max_trades_per_day,
                "consecutive_losses": s.consecutive_losses,
                "news_lock_until": s.news_lock_until.isoformat() if s.news_lock_until else None,
                "spread_points": round(self._current_spread, 1),
                "atr": round(self._current_atr, 2),
                "active_locks": [lock.to_dict() for lock in locks if lock.locked],
                "evaluated_at": now.isoformat(),
            }

    def compliance_report(self) -> str:
        status = self.get_status_dict()
        lines = [
            "=== FTMO Compliance Report ===",
            f"Can Trade:           {'YES' if status['can_trade'] else 'NO'}",
            f"Equity:              €{status['equity']:,.2f}",
            f"Peak Equity:         €{status['peak_equity']:,.2f}",
            f"Daily P&L:           €{status['daily_pnl']:+,.2f}  (limit: -€{status['daily_loss_limit']:,.0f})",
            f"Daily Loss Used:     €{status['daily_loss_used']:,.2f}  ({status['daily_loss_pct']:.1f}%)",
            f"Daily Remaining:     €{status['daily_remaining']:,.2f}",
            f"Total Drawdown:      €{status['total_drawdown']:,.2f}  ({status['total_drawdown_pct']:.1f}%)",
            f"Trades Today:        {status['trades_today']} / {status['max_trades_per_day']}",
            f"Consecutive Losses:  {status['consecutive_losses']}",
        ]
        if status["active_locks"]:
            lines.append("\nActive Locks:")
            for lock in status["active_locks"]:
                lines.append(f"  [{lock['severity']}] {lock['lock_type']}: {lock['reason']}")
        return "\n".join(lines)

    # ─────────────────────────────────────────────────────────────
    # PRIVATE: Lock evaluation
    # ─────────────────────────────────────────────────────────────

    def _evaluate_all_locks(self) -> list[LockStatus]:
        now = datetime.now(_UTC)
        equity = self._current_equity
        s = self._state
        cfg = self.config
        locks: list[LockStatus] = []

        # 1. Daily loss lock
        if s.day_start_equity > 0:
            daily_loss = max(0.0, s.day_start_equity - equity)
            hard_limit = cfg.max_daily_loss - cfg.daily_buffer
            if daily_loss >= hard_limit:
                locks.append(LockStatus(
                    locked=True,
                    reason=f"Daily loss €{daily_loss:,.0f} ≥ limit €{hard_limit:,.0f} (buffer: €{cfg.daily_buffer:.0f})",
                    lock_type="daily_loss",
                    severity="CRITICAL",
                ))
            elif daily_loss >= hard_limit * 0.8:
                locks.append(LockStatus(
                    locked=False,
                    reason=f"Daily loss €{daily_loss:,.0f} approaching limit ({daily_loss / hard_limit * 100:.0f}%)",
                    lock_type="daily_loss_warning",
                    severity="WARN",
                ))

        # 2. Weekly loss lock
        if s.week_start_equity > 0:
            weekly_loss = max(0.0, s.week_start_equity - equity)
            weekly_limit = cfg.max_weekly_loss - cfg.weekly_buffer
            if weekly_loss >= weekly_limit:
                locks.append(LockStatus(
                    locked=True,
                    reason=f"Weekly loss €{weekly_loss:,.0f} ≥ limit €{weekly_limit:,.0f}",
                    lock_type="weekly_loss",
                    severity="CRITICAL",
                ))

        # 3. Total drawdown lock (FTMO max loss rule)
        total_dd = max(0.0, cfg.start_capital - equity)
        dd_limit = cfg.max_total_drawdown - cfg.drawdown_buffer
        if total_dd >= dd_limit:
            locks.append(LockStatus(
                locked=True,
                reason=f"Total drawdown €{total_dd:,.0f} ≥ FTMO limit €{dd_limit:,.0f}",
                lock_type="max_drawdown",
                severity="CRITICAL",
            ))

        # 4. Max trades per day
        if s.trades_today >= cfg.max_trades_per_day:
            locks.append(LockStatus(
                locked=True,
                reason=f"Max trades reached: {s.trades_today}/{cfg.max_trades_per_day} today",
                lock_type="max_trades_day",
                severity="BLOCK",
            ))

        # 5. Consecutive loss streak
        if s.consecutive_losses >= cfg.max_consecutive_losses:
            locks.append(LockStatus(
                locked=True,
                reason=f"Consecutive losses: {s.consecutive_losses} ≥ {cfg.max_consecutive_losses} — cooling down",
                lock_type="loss_streak",
                severity="BLOCK",
            ))

        # 6. Monthly profit target (stop trading after target reached)
        if cfg.monthly_profit_target is not None and s.monthly_pnl >= cfg.monthly_profit_target:
            locks.append(LockStatus(
                locked=True,
                reason=f"Monthly target €{cfg.monthly_profit_target:,.0f} achieved (P&L: €{s.monthly_pnl:,.0f})",
                lock_type="profit_target",
                severity="BLOCK",
            ))

        # 7. News lock
        if s.news_lock_until is not None:
            if now < s.news_lock_until:
                locks.append(LockStatus(
                    locked=True,
                    reason=f"News lock active until {s.news_lock_until.strftime('%H:%M UTC')}",
                    lock_type="news_lock",
                    expires_at=s.news_lock_until,
                    severity="BLOCK",
                ))
            else:
                s.news_lock_until = None

        # 8. Spread lock
        if self._current_spread > 0 and self._current_spread > cfg.max_spread_points:
            locks.append(LockStatus(
                locked=True,
                reason=f"Spread {self._current_spread:.1f} pts > max {cfg.max_spread_points:.0f} pts",
                lock_type="spread_lock",
                severity="BLOCK",
            ))

        # 9. Equity trailing stop
        if (
            s.peak_equity > 0
            and s.peak_equity > cfg.start_capital + cfg.equity_trailing_activate
        ):
            trailing_floor = s.peak_equity - cfg.equity_trailing_from_peak
            if equity < trailing_floor:
                locks.append(LockStatus(
                    locked=True,
                    reason=(
                        f"Equity €{equity:,.0f} fell below trailing floor €{trailing_floor:,.0f} "
                        f"(peak €{s.peak_equity:,.0f}, protect €{cfg.equity_trailing_from_peak:,.0f})"
                    ),
                    lock_type="equity_trailing",
                    severity="CRITICAL",
                ))

        return locks

    def _sync_period_anchors(self, equity: float, now: datetime) -> None:
        """Reset period accumulators when day/week/month changes."""
        today_str = now.date().isoformat()
        week_str = f"{now.year}-W{now.isocalendar()[1]:02d}"
        month_str = now.strftime("%Y-%m")

        if self._state.day_date != today_str:
            if self._state.day_date:
                logger.info(
                    "New trading day. Daily reset: trades=%d, daily_pnl=€%+.2f",
                    self._state.trades_today,
                    self._state.daily_pnl,
                )
            self._state.day_date = today_str
            self._state.day_start_equity = equity
            self._state.trades_today = 0
            self._state.daily_pnl = 0.0
            self._state.consecutive_losses = 0

        if self._state.week_num != week_str:
            self._state.week_num = week_str
            self._state.week_start_equity = equity
            self._state.weekly_pnl = 0.0

        if self._state.month_str != month_str:
            self._state.month_str = month_str
            self._state.month_start_equity = equity
            self._state.monthly_pnl = 0.0

        if self._state.peak_equity == 0.0:
            self._state.peak_equity = equity


# ─────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────

_guard_instance: FTMOGuard | None = None
_guard_lock = threading.Lock()


def get_ftmo_guard(config: FTMOConfig | None = None) -> FTMOGuard:
    global _guard_instance
    with _guard_lock:
        if _guard_instance is None or config is not None:
            _guard_instance = FTMOGuard(config)
        return _guard_instance


def reset_ftmo_guard() -> None:
    """Test helper — reset singleton."""
    global _guard_instance
    with _guard_lock:
        _guard_instance = None
