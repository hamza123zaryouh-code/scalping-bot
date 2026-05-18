"""
XAUUSD Event Calendar Engine — Macro Event Protection
======================================================
Automatische trading blokkade voor high-impact USD/Gold events:
  - FOMC (Federal Open Market Committee)
  - NFP (Non-Farm Payrolls)
  - CPI (Consumer Price Index)
  - Interest Rate Decisions
  - Powell / Fed speeches
  - PCE (Personal Consumption Expenditures)
  - PPI (Producer Price Index)
  - GDP releases

Gedrag:
  - Blokkeert nieuwe trades X minuten voor het event
  - Blokkeert nieuwe trades Y minuten na het event
  - Cache: events worden maximaal 1x per dag opgehaald
  - Graceful fallback bij API failure (geen blokkade bij onzekerheid)
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────

DEFAULT_BLOCK_BEFORE_MINUTES = int(os.getenv("EVENT_BLOCK_BEFORE_MINUTES", "30"))
DEFAULT_BLOCK_AFTER_MINUTES = int(os.getenv("EVENT_BLOCK_AFTER_MINUTES", "60"))
HIGH_IMPACT_ONLY = os.getenv("EVENT_HIGH_IMPACT_ONLY", "true").lower() in ("1", "true", "yes")

CACHE_DIR = Path("live_logs")
CALENDAR_CACHE_FILE = CACHE_DIR / "event_calendar_cache.json"
CACHE_MAX_AGE_HOURS = 6

# Hardcoded keyword filters for high-impact USD events
HIGH_IMPACT_KEYWORDS = [
    "fomc",
    "federal open market",
    "fed rate",
    "interest rate decision",
    "nfp",
    "non-farm payroll",
    "nonfarm payroll",
    "cpi",
    "consumer price index",
    "pce",
    "personal consumption",
    "ppi",
    "producer price",
    "powell",
    "fed chair",
    "federal reserve",
    "gdp",
    "gross domestic product",
    "unemployment rate",
    "jobless claims",
    "ism manufacturing",
    "ism services",
    "retail sales",
    "core retail",
    "jackson hole",
]

MEDIUM_IMPACT_KEYWORDS = [
    "aud",
    "gbp",
    "eur",
    "jpy",
    "cad",
    "chf",
    "ecb",
    "boe",
    "boj",
    "rba",
    "bank of england",
    "uk cpi",
    "eu cpi",
    "eurozone",
]


@dataclass
class EconomicEvent:
    """Een enkel economisch event."""

    name: str
    event_time: datetime  # UTC
    impact: str  # "high" | "medium" | "low"
    currency: str  # "USD" | "EUR" etc.
    source: str = "manual"
    description: str = ""

    @property
    def is_gold_relevant(self) -> bool:
        name_lower = self.name.lower()
        return self.currency == "USD" or any(kw in name_lower for kw in ["gold", "xau", "silver", "commodit"])

    @property
    def is_high_impact(self) -> bool:
        name_lower = self.name.lower()
        return self.impact == "high" or any(kw in name_lower for kw in HIGH_IMPACT_KEYWORDS)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "event_time": self.event_time.isoformat(),
            "impact": self.impact,
            "currency": self.currency,
            "source": self.source,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: dict) -> EconomicEvent:
        return cls(
            name=d["name"],
            event_time=datetime.fromisoformat(d["event_time"]),
            impact=d.get("impact", "medium"),
            currency=d.get("currency", "USD"),
            source=d.get("source", "cached"),
            description=d.get("description", ""),
        )


@dataclass
class EventWindow:
    """Actief event blokkeringsvenster."""

    event: EconomicEvent
    block_from: datetime
    block_until: datetime
    is_active: bool

    def minutes_until_start(self, now: datetime) -> float:
        delta = (self.block_from - now).total_seconds() / 60
        return max(0.0, delta)

    def minutes_until_end(self, now: datetime) -> float:
        delta = (self.block_until - now).total_seconds() / 60
        return max(0.0, delta)


@dataclass
class CalendarStatus:
    """Status van de event kalender op dit moment."""

    is_blocked: bool
    block_reason: str | None
    active_event: EconomicEvent | None
    next_event: EconomicEvent | None
    minutes_until_next_block: float | None
    minutes_until_unblock: float | None
    risk_level: str  # "clear" | "warning" | "blocked"
    upcoming_events: list[EconomicEvent] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "is_blocked": self.is_blocked,
            "block_reason": self.block_reason,
            "active_event": self.active_event.to_dict() if self.active_event else None,
            "next_event": self.next_event.to_dict() if self.next_event else None,
            "minutes_until_next_block": round(self.minutes_until_next_block, 1)
            if self.minutes_until_next_block is not None
            else None,
            "minutes_until_unblock": round(self.minutes_until_unblock, 1)
            if self.minutes_until_unblock is not None
            else None,
            "risk_level": self.risk_level,
            "upcoming_events": [e.to_dict() for e in self.upcoming_events[:5]],
        }


class EventCalendar:
    """
    Economic calendar engine voor XAUUSD macro event protection.

    Gebruik:
        cal = EventCalendar()
        status = cal.get_status()
        if not cal.can_trade():
            logger.warning("Event blokkade: %s", cal.get_status().block_reason)
    """

    def __init__(
        self,
        block_before_minutes: int = DEFAULT_BLOCK_BEFORE_MINUTES,
        block_after_minutes: int = DEFAULT_BLOCK_AFTER_MINUTES,
        high_impact_only: bool = HIGH_IMPACT_ONLY,
    ):
        self._block_before = block_before_minutes
        self._block_after = block_after_minutes
        self._high_impact_only = high_impact_only
        self._events: list[EconomicEvent] = []
        self._last_fetch: float = 0.0
        self._cache_max_age = CACHE_MAX_AGE_HOURS * 3600

        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self._load_hardcoded_events()
        self._load_cache()

    # ─────────────────────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────────────────────

    def can_trade(self, now: datetime | None = None) -> bool:
        """True als trading niet geblokkeerd is door een event."""
        return not self.get_status(now).is_blocked

    def get_status(self, now: datetime | None = None) -> CalendarStatus:
        """Volledige status van de event kalender."""
        if now is None:
            now = datetime.now(timezone.utc)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        self._maybe_refresh()
        events = self._get_relevant_events()
        windows = [self._make_window(e) for e in events]

        # Check actieve blokkade
        active_window: EventWindow | None = None
        for window in windows:
            if window.block_from <= now <= window.block_until:
                active_window = window
                break

        if active_window:
            return CalendarStatus(
                is_blocked=True,
                block_reason=f"{active_window.event.name} — trading geblokkeerd",
                active_event=active_window.event,
                next_event=self._next_event(now, skip=active_window.event),
                minutes_until_next_block=None,
                minutes_until_unblock=active_window.minutes_until_end(now),
                risk_level="blocked",
                upcoming_events=self._upcoming_events(now, limit=5),
            )

        # Geen actieve blokkade — check aankomende events
        next_window: EventWindow | None = None
        for window in sorted(windows, key=lambda w: w.block_from):
            if window.block_from > now:
                next_window = window
                break

        if next_window:
            mins_until = next_window.minutes_until_start(now)
            risk_level = "warning" if mins_until <= 60 else "clear"
            return CalendarStatus(
                is_blocked=False,
                block_reason=None,
                active_event=None,
                next_event=next_window.event,
                minutes_until_next_block=mins_until,
                minutes_until_unblock=None,
                risk_level=risk_level,
                upcoming_events=self._upcoming_events(now, limit=5),
            )

        return CalendarStatus(
            is_blocked=False,
            block_reason=None,
            active_event=None,
            next_event=None,
            minutes_until_next_block=None,
            minutes_until_unblock=None,
            risk_level="clear",
            upcoming_events=self._upcoming_events(now, limit=5),
        )

    def add_event(self, event: EconomicEvent) -> None:
        """Voeg een event handmatig toe (bijv. vanuit Telegram)."""
        self._events.append(event)
        self._save_cache()
        logger.info("Event toegevoegd: %s @ %s", event.name, event.event_time.isoformat())

    def upcoming_events(self, hours: int = 48) -> list[EconomicEvent]:
        """Geeft aankomende events terug binnen de opgegeven uren."""
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(hours=hours)
        return [e for e in self._get_relevant_events() if now <= e.event_time <= cutoff]

    def fetch_from_api(self) -> bool:
        """
        Probeer events op te halen van een externe bron.
        Fallback: gebruikt hardcoded events als de API niet beschikbaar is.
        """
        fetched = self._fetch_investingcom_calendar()
        if not fetched:
            fetched = self._fetch_forexfactory_calendar()
        if fetched:
            self._last_fetch = time.time()
            self._save_cache()
            logger.info("Economic calendar bijgewerkt: %d events", len(self._events))
        return fetched

    # ─────────────────────────────────────────────────────────────
    # PRIVÉ METHODEN
    # ─────────────────────────────────────────────────────────────

    def _maybe_refresh(self) -> None:
        age = time.time() - self._last_fetch
        if age > self._cache_max_age:
            self.fetch_from_api()

    def _get_relevant_events(self) -> list[EconomicEvent]:
        """Filter events op relevantie voor XAUUSD."""
        now = datetime.now(timezone.utc)
        # Bekijk events in een raam van 7 dagen terug tot 7 dagen vooruit
        start = now - timedelta(days=1)
        end = now + timedelta(days=7)

        relevant = []
        for e in self._events:
            if not (start <= e.event_time <= end):
                continue
            if not e.is_gold_relevant:
                continue
            if self._high_impact_only and not e.is_high_impact:
                continue
            relevant.append(e)

        return sorted(relevant, key=lambda e: e.event_time)

    def _make_window(self, event: EconomicEvent) -> EventWindow:
        now = datetime.now(timezone.utc)
        block_from = event.event_time - timedelta(minutes=self._block_before)
        block_until = event.event_time + timedelta(minutes=self._block_after)
        return EventWindow(
            event=event,
            block_from=block_from,
            block_until=block_until,
            is_active=block_from <= now <= block_until,
        )

    def _next_event(self, now: datetime, skip: EconomicEvent | None = None) -> EconomicEvent | None:
        events = [e for e in self._get_relevant_events() if e.event_time > now]
        if skip:
            events = [e for e in events if e.name != skip.name]
        return events[0] if events else None

    def _upcoming_events(self, now: datetime, limit: int = 5) -> list[EconomicEvent]:
        return [e for e in self._get_relevant_events() if e.event_time >= now][:limit]

    def _load_hardcoded_events(self) -> None:
        """Laad bekende terugkerende events (maandelijks/quarterly hardcoded schema)."""
        now = datetime.now(timezone.utc)
        year = now.year
        month = now.month

        hardcoded = []

        # NFP: eerste vrijdag van elke maand, 13:30 UTC
        for m in range(max(1, month - 1), min(13, month + 3)):
            nfp_day = self._first_weekday_of_month(year, m, weekday=4)  # vrijdag
            if nfp_day:
                hardcoded.append(
                    EconomicEvent(
                        name="NFP Non-Farm Payrolls",
                        event_time=datetime(year, m, nfp_day, 13, 30, tzinfo=timezone.utc),
                        impact="high",
                        currency="USD",
                        source="hardcoded",
                        description="Maandelijks werkgelegenheidsrapport — hoogste impact op goud",
                    )
                )

        # CPI: ca. de 10e-15e van elke maand, 13:30 UTC (hardcoded midden)
        for m in range(max(1, month - 1), min(13, month + 3)):
            hardcoded.append(
                EconomicEvent(
                    name="CPI Consumer Price Index",
                    event_time=datetime(year, m, 12, 13, 30, tzinfo=timezone.utc),
                    impact="high",
                    currency="USD",
                    source="hardcoded",
                    description="Inflatie indicator — grote impact op Fed beleid en goud",
                )
            )

        # FOMC: 8x per jaar (quarterly + extra); approximate planning
        fomc_months = [1, 3, 5, 6, 7, 9, 11, 12]
        for m in fomc_months:
            if abs(m - month) <= 2:
                hardcoded.append(
                    EconomicEvent(
                        name="FOMC Interest Rate Decision",
                        event_time=datetime(year, m, 20, 19, 0, tzinfo=timezone.utc),
                        impact="high",
                        currency="USD",
                        source="hardcoded",
                        description="Federal Reserve rentebesluit — maximale impact op goud",
                    )
                )

        # PCE: laatste vrijdag van elke maand
        for m in range(max(1, month - 1), min(13, month + 3)):
            pce_day = self._last_weekday_of_month(year, m, weekday=4)
            if pce_day:
                hardcoded.append(
                    EconomicEvent(
                        name="PCE Core Inflation",
                        event_time=datetime(year, m, pce_day, 13, 30, tzinfo=timezone.utc),
                        impact="high",
                        currency="USD",
                        source="hardcoded",
                        description="Fed's favoriete inflatiemaat — rechtstreeks effect op goud",
                    )
                )

        self._events.extend(hardcoded)
        logger.debug("Hardcoded events geladen: %d events", len(hardcoded))

    def _load_cache(self) -> None:
        """Laad gecachede events van schijf."""
        if not CALENDAR_CACHE_FILE.exists():
            return
        try:
            data = json.loads(CALENDAR_CACHE_FILE.read_text(encoding="utf-8"))
            cached_events = [EconomicEvent.from_dict(e) for e in data.get("events", [])]
            self._last_fetch = float(data.get("fetched_at", 0))

            cache_age = time.time() - self._last_fetch
            if cache_age < self._cache_max_age:
                # Voeg gecachede events toe die niet al aanwezig zijn
                existing_keys = {(e.name, e.event_time.isoformat()) for e in self._events}
                for ev in cached_events:
                    key = (ev.name, ev.event_time.isoformat())
                    if key not in existing_keys:
                        self._events.append(ev)
                logger.debug("Event cache geladen: %d extra events", len(cached_events))
        except Exception as exc:
            logger.warning("Event cache laden mislukt: %s", exc)

    def _save_cache(self) -> None:
        """Sla events op in cache."""
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                "fetched_at": time.time(),
                "events": [e.to_dict() for e in self._events],
            }
            CALENDAR_CACHE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Event cache opslaan mislukt: %s", exc)

    def _fetch_investingcom_calendar(self) -> bool:
        """Probeer economic calendar op te halen via requests (geen API key vereist)."""
        try:
            import requests

            headers = {
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            }

            # ForexFactory XML feed (publiek beschikbaar)
            url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
            resp = requests.get(url, headers=headers, timeout=10)

            if resp.status_code != 200:
                return False

            events_data = resp.json()
            new_events = []

            for item in events_data:
                try:
                    title = item.get("title", "")
                    impact = item.get("impact", "").lower()
                    currency = item.get("country", "").upper()
                    date_str = item.get("date", "")

                    if not date_str or not title:
                        continue

                    event_time = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                    if event_time.tzinfo is None:
                        event_time = event_time.replace(tzinfo=timezone.utc)

                    ev = EconomicEvent(
                        name=title,
                        event_time=event_time,
                        impact=impact if impact in ("high", "medium", "low") else "medium",
                        currency=currency,
                        source="forexfactory_api",
                    )
                    new_events.append(ev)
                except Exception:
                    continue

            if new_events:
                # Vervang API-events (niet hardcoded) door verse data
                self._events = [e for e in self._events if e.source == "hardcoded"]
                self._events.extend(new_events)
                return True

        except Exception as exc:
            logger.debug("ForexFactory API fetch mislukt: %s", exc)

        return False

    def _fetch_forexfactory_calendar(self) -> bool:
        """Fallback: haal calendar op via alternatieve bron."""
        try:
            import requests

            resp = requests.get(
                "https://economic-calendar.tradingeconomics.com/calendar",
                params={"c": "united states", "d1": datetime.now(timezone.utc).strftime("%Y-%m-%d")},
                timeout=8,
            )
            if resp.status_code == 200:
                # Probeer JSON te parsen
                data = resp.json()
                if isinstance(data, list) and data:
                    return True
        except Exception as exc:
            logger.debug("TradingEconomics calendar fetch mislukt: %s", exc)

        return False

    @staticmethod
    def _first_weekday_of_month(year: int, month: int, weekday: int) -> int | None:
        """Geeft de dag van de eerste occurrence van 'weekday' in de maand (0=Mon, 4=Fri)."""
        try:
            from calendar import monthrange

            first_day_wd = datetime(year, month, 1).weekday()
            diff = (weekday - first_day_wd) % 7
            day = 1 + diff
            _, days_in_month = monthrange(year, month)
            return day if day <= days_in_month else None
        except Exception:
            return None

    @staticmethod
    def _last_weekday_of_month(year: int, month: int, weekday: int) -> int | None:
        """Geeft de dag van de laatste occurrence van 'weekday' in de maand."""
        try:
            from calendar import monthrange

            _, days_in_month = monthrange(year, month)
            last_day = datetime(year, month, days_in_month)
            diff = (last_day.weekday() - weekday) % 7
            day = days_in_month - diff
            return day if day >= 1 else None
        except Exception:
            return None


# ─────────────────────────────────────────────────────────────────
# SINGLETON
# ─────────────────────────────────────────────────────────────────

_calendar_instance: EventCalendar | None = None


def get_calendar() -> EventCalendar:
    global _calendar_instance
    if _calendar_instance is None:
        _calendar_instance = EventCalendar()
    return _calendar_instance
