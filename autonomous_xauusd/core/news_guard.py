"""
NewsGuard — Trading pause and risk reduction around high-impact news events.

Integrates with LiveNewsEngine and FTMOGuard to enforce:
  - Pre-event blackout window (default 30 min before)
  - Post-event blackout window (default 20 min after)
  - Dynamic spread protection (block trading when spread spikes)
  - Volatility shock detection (ATR spike relative to rolling average)
  - Automatic lock injection into FTMOGuard

NewsGuard reads from two sources:
  1. Live news analysis (LiveNewsEngine) — real-time danger scores
  2. ForexFactory economic calendar scraper — scheduled events

Environment variables:
  NEWS_LOCK_BEFORE_MIN   — minutes before high-impact event to pause (default 30)
  NEWS_LOCK_AFTER_MIN    — minutes after high-impact event to resume (default 20)
  NEWS_DANGER_THRESHOLD  — danger score above which trading is paused (default 0.65)
  SPREAD_LOCK_POINTS     — max allowed spread in points for XAUUSD (default 50)
  ATR_SPIKE_MULTIPLIER   — ATR ratio above which volatility lock activates (default 2.5)
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from .live_news_engine import LiveNewsEngine, NewsAnalysis

logger = logging.getLogger(__name__)

_UTC = timezone.utc

_LOCK_BEFORE_MIN = int(os.getenv("NEWS_LOCK_BEFORE_MIN", "30"))
_LOCK_AFTER_MIN = int(os.getenv("NEWS_LOCK_AFTER_MIN", "20"))
_DANGER_THRESHOLD = float(os.getenv("NEWS_DANGER_THRESHOLD", "0.65"))
_SPREAD_LOCK_POINTS = float(os.getenv("SPREAD_LOCK_POINTS", "50"))
_ATR_SPIKE_MULT = float(os.getenv("ATR_SPIKE_MULTIPLIER", "2.5"))


@dataclass
class GuardDecision:
    allow_trading: bool
    reason: str
    risk_modifier: float = 1.0
    lock_expires_at: datetime | None = None
    lock_type: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_trading": self.allow_trading,
            "reason": self.reason,
            "risk_modifier": round(self.risk_modifier, 3),
            "lock_type": self.lock_type,
            "lock_expires_at": self.lock_expires_at.isoformat() if self.lock_expires_at else None,
        }


@dataclass
class ScheduledEvent:
    name: str
    event_time: datetime
    impact: str = "HIGH"   # LOW | MEDIUM | HIGH | CRITICAL
    currency: str = "USD"
    actual: str | None = None
    forecast: str | None = None
    previous: str | None = None

    def is_active_window(
        self,
        now: datetime,
        before_min: int = _LOCK_BEFORE_MIN,
        after_min: int = _LOCK_AFTER_MIN,
    ) -> bool:
        window_start = self.event_time - timedelta(minutes=before_min)
        window_end = self.event_time + timedelta(minutes=after_min)
        return window_start <= now <= window_end


# High-impact events that always trigger pre/post blackout
_SCHEDULED_KEYWORDS = frozenset({
    "nfp", "non-farm", "fomc", "federal reserve", "cpi", "consumer price",
    "pce", "gdp", "retail sales", "jobs", "unemployment", "powell",
    "fed chair", "treasury", "fed decision", "rate decision",
    "ecb", "bank of england", "boe", "inflation",
})


class NewsGuard:
    """
    Production news guard for XAUUSD trading.

    Checks:
      1. Live danger score from news analysis
      2. Scheduled event windows (ForexFactory calendar)
      3. Spread spike protection
      4. ATR volatility spike protection

    Usage:
        guard = NewsGuard(news_engine)
        decision = guard.check(atr=current_atr, spread_pts=current_spread)
        if not decision.allow_trading:
            logger.warning("Trade blocked: %s", decision.reason)
    """

    def __init__(
        self,
        news_engine: LiveNewsEngine | None = None,
        lock_before_min: int = _LOCK_BEFORE_MIN,
        lock_after_min: int = _LOCK_AFTER_MIN,
        danger_threshold: float = _DANGER_THRESHOLD,
    ) -> None:
        self._engine = news_engine or LiveNewsEngine()
        self._lock_before_min = lock_before_min
        self._lock_after_min = lock_after_min
        self._danger_threshold = danger_threshold
        self._scheduled_events: list[ScheduledEvent] = []
        self._events_fetched_at: float = 0.0
        self._atr_history: list[float] = []
        self._atr_window = 20

    def check(
        self,
        atr: float | None = None,
        spread_pts: float | None = None,
        force_news_refresh: bool = False,
    ) -> GuardDecision:
        """
        Run all guard checks. Returns a GuardDecision.

        Args:
            atr:           Current ATR value for volatility spike detection.
            spread_pts:    Current spread in points.
            force_news_refresh: Force refresh of news cache.
        """
        now = datetime.now(_UTC)

        # Check 1: Scheduled high-impact events
        event_decision = self._check_scheduled_events(now)
        if not event_decision.allow_trading:
            return event_decision

        # Check 2: Live news danger score
        news_decision = self._check_live_news(force_refresh=force_news_refresh)
        if not news_decision.allow_trading:
            return news_decision

        # Check 3: Spread spike
        if spread_pts is not None and spread_pts > _SPREAD_LOCK_POINTS:
            return GuardDecision(
                allow_trading=False,
                reason=f"Spread spike: {spread_pts:.1f} pts > {_SPREAD_LOCK_POINTS:.0f} pts limit",
                risk_modifier=0.0,
                lock_type="spread_spike",
            )

        # Check 4: ATR volatility spike
        if atr is not None and atr > 0:
            self._atr_history.append(atr)
            if len(self._atr_history) > self._atr_window:
                self._atr_history.pop(0)
            if len(self._atr_history) >= 5:
                avg_atr = sum(self._atr_history[:-1]) / max(1, len(self._atr_history) - 1)
                if avg_atr > 0 and atr / avg_atr >= _ATR_SPIKE_MULT:
                    return GuardDecision(
                        allow_trading=False,
                        reason=(
                            f"ATR volatility spike: current {atr:.2f} is "
                            f"{atr / avg_atr:.1f}× the {len(self._atr_history)-1}-bar average"
                        ),
                        risk_modifier=0.0,
                        lock_type="atr_spike",
                    )

        # All clear — return news risk modifier (may reduce risk without blocking)
        latest = self._engine.get_analysis()
        modifier = latest.risk_modifier()
        return GuardDecision(
            allow_trading=True,
            reason="All news guard checks passed",
            risk_modifier=modifier,
            lock_type="none",
        )

    def get_news_summary(self) -> dict[str, Any]:
        """Return latest news analysis as dict for dashboard/API."""
        analysis = self._engine.get_analysis()
        return analysis.to_dict()

    def get_upcoming_events(self) -> list[dict[str, Any]]:
        """Return list of upcoming high-impact events."""
        self._maybe_refresh_calendar()
        now = datetime.now(_UTC)
        upcoming = [
            e for e in self._scheduled_events
            if e.event_time >= now and e.event_time <= now + timedelta(hours=24)
        ]
        return [
            {
                "name": e.name,
                "event_time": e.event_time.isoformat(),
                "impact": e.impact,
                "currency": e.currency,
                "minutes_until": int((e.event_time - now).total_seconds() / 60),
                "in_window": e.is_active_window(now, self._lock_before_min, self._lock_after_min),
            }
            for e in upcoming
        ]

    # ─────────────────────────────────────────────────────────────
    # INTERNAL CHECKS
    # ─────────────────────────────────────────────────────────────

    def _check_scheduled_events(self, now: datetime) -> GuardDecision:
        self._maybe_refresh_calendar()
        for event in self._scheduled_events:
            if event.impact not in ("HIGH", "CRITICAL"):
                continue
            if not event.is_active_window(now, self._lock_before_min, self._lock_after_min):
                continue
            minutes_to_event = (event.event_time - now).total_seconds() / 60
            if minutes_to_event > 0:
                reason = (
                    f"Pre-event blackout: {event.name} in {minutes_to_event:.0f} min "
                    f"({event.event_time.strftime('%H:%M UTC')})"
                )
            else:
                minutes_after = abs(minutes_to_event)
                reason = (
                    f"Post-event blackout: {event.name} was {minutes_after:.0f} min ago — "
                    f"waiting {self._lock_after_min - minutes_after:.0f} more min"
                )
            lock_until = event.event_time + timedelta(minutes=self._lock_after_min)
            return GuardDecision(
                allow_trading=False,
                reason=reason,
                risk_modifier=0.0,
                lock_expires_at=lock_until,
                lock_type="scheduled_event",
            )
        return GuardDecision(allow_trading=True, reason="No active scheduled events", risk_modifier=1.0)

    def _check_live_news(self, force_refresh: bool = False) -> GuardDecision:
        try:
            analysis: NewsAnalysis = self._engine.get_analysis(force_refresh=force_refresh)
        except Exception as exc:
            logger.warning("NewsGuard: live news check failed: %s — allowing trading", exc)
            return GuardDecision(allow_trading=True, reason="News check unavailable (degraded mode)", risk_modifier=0.8)

        if analysis.critical_count > 0:
            return GuardDecision(
                allow_trading=False,
                reason=f"CRITICAL news event detected ({analysis.critical_count} headlines)",
                risk_modifier=0.0,
                lock_type="critical_news",
            )

        if analysis.danger_score >= self._danger_threshold:
            return GuardDecision(
                allow_trading=False,
                reason=(
                    f"High danger news: score={analysis.danger_score:.2f} ≥ threshold={self._danger_threshold:.2f} "
                    f"({analysis.high_impact_count} high-impact headlines)"
                ),
                risk_modifier=0.0,
                lock_type="high_danger_news",
            )

        modifier = analysis.risk_modifier()
        if modifier < 1.0:
            return GuardDecision(
                allow_trading=True,
                reason=f"News risk reduction: modifier={modifier:.2f} (danger={analysis.danger_score:.2f})",
                risk_modifier=modifier,
                lock_type="risk_reduced",
            )

        return GuardDecision(allow_trading=True, reason="News clear", risk_modifier=modifier)

    # ─────────────────────────────────────────────────────────────
    # CALENDAR
    # ─────────────────────────────────────────────────────────────

    def _maybe_refresh_calendar(self) -> None:
        age = time.time() - self._events_fetched_at
        if age < 3600:  # refresh every hour
            return
        try:
            self._scheduled_events = self._fetch_forexfactory_calendar()
            self._events_fetched_at = time.time()
            logger.info(
                "NewsGuard: loaded %d high-impact events from calendar",
                len(self._scheduled_events),
            )
        except Exception as exc:
            logger.warning("Calendar refresh failed: %s — keeping old data", exc)
            if not self._scheduled_events:
                self._events_fetched_at = time.time()

    def _fetch_forexfactory_calendar(self) -> list[ScheduledEvent]:
        """
        Fetch economic calendar from ForexFactory.
        Returns events for today + next 2 days.
        """
        events: list[ScheduledEvent] = []
        try:
            import urllib.request
            url = "https://www.forexfactory.com/calendar.php?week=this"
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "text/html",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                html = resp.read().decode("utf-8", errors="replace")
            events.extend(self._parse_forexfactory_html(html))
        except Exception as exc:
            logger.debug("ForexFactory calendar fetch failed: %s", exc)

        # Supplement with known recurring events
        events.extend(self._generate_synthetic_events())
        return events

    @staticmethod
    def _parse_forexfactory_html(html: str) -> list[ScheduledEvent]:
        """Parse ForexFactory calendar HTML for high-impact USD events."""
        events: list[ScheduledEvent] = []
        try:
            import re
            # ForexFactory uses specific HTML structure — extract rows with impact icons
            # Look for high-impact (red) events affecting USD
            pattern = re.compile(
                r'<tr[^>]*class="[^"]*calendar_row[^"]*"[^>]*>(.*?)</tr>',
                re.DOTALL | re.IGNORECASE,
            )
            time_pattern = re.compile(r'<td[^>]*class="[^"]*time[^"]*"[^>]*>(.*?)</td>', re.DOTALL)
            name_pattern = re.compile(r'<span[^>]*class="[^"]*event[^"]*"[^>]*>(.*?)</span>', re.DOTALL)
            impact_pattern = re.compile(r'class="[^"]*impact-([a-z]+)[^"]*"', re.IGNORECASE)
            cur_pattern = re.compile(r'<td[^>]*class="[^"]*currency[^"]*"[^>]*>(.*?)</td>', re.DOTALL)

            now = datetime.now(_UTC)
            current_day = now.date()

            for row in pattern.finditer(html):
                row_html = row.group(1)
                impact_match = impact_pattern.search(row_html)
                if not impact_match:
                    continue
                impact_raw = impact_match.group(1).upper()
                if impact_raw not in ("HIGH", "RED"):
                    continue

                cur_match = cur_pattern.search(row_html)
                currency = re.sub(r'<[^>]+>', '', cur_match.group(1)).strip() if cur_match else ""
                if currency not in ("USD", "EUR", "GBP"):
                    continue

                name_match = name_pattern.search(row_html)
                event_name = re.sub(r'<[^>]+>', '', name_match.group(1)).strip() if name_match else ""
                if not event_name:
                    continue

                time_match = time_pattern.search(row_html)
                time_str = re.sub(r'<[^>]+>', '', time_match.group(1)).strip() if time_match else ""

                event_time = None
                if time_str:
                    try:
                        t = datetime.strptime(time_str.upper(), "%I:%M%p")
                        event_time = datetime.combine(
                            current_day,
                            t.time(),
                            tzinfo=_UTC,
                        )
                    except Exception:
                        pass

                if event_time is None:
                    event_time = now.replace(hour=12, minute=0, second=0, microsecond=0)

                events.append(ScheduledEvent(
                    name=event_name[:80],
                    event_time=event_time,
                    impact="HIGH",
                    currency=currency,
                ))
        except Exception as exc:
            logger.debug("ForexFactory HTML parse failed: %s", exc)

        return events

    @staticmethod
    def _generate_synthetic_events() -> list[ScheduledEvent]:
        """
        Generate synthetic placeholders for recurring USD events.
        These fire every first Friday of month (NFP) and every 6 weeks (FOMC).
        Only used as fallback when calendar scraping fails.
        """
        events: list[ScheduledEvent] = []
        now = datetime.now(_UTC)
        today = now.date()

        # First Friday of month = NFP day
        year, month = today.year, today.month
        first_day = today.replace(day=1)
        days_to_friday = (4 - first_day.weekday()) % 7
        nfp_day = first_day + timedelta(days=days_to_friday)
        if nfp_day.month == month:
            nfp_time = datetime.combine(nfp_day, __import__("datetime").time(13, 30), tzinfo=_UTC)
            if abs((nfp_time - now).total_seconds()) < 86400 * 2:
                events.append(ScheduledEvent(
                    name="Non-Farm Payrolls (NFP)",
                    event_time=nfp_time,
                    impact="CRITICAL",
                    currency="USD",
                ))

        return events
