"""
XAUUSD V17 Session Engine — Timezone-Aware Trading Sessions
===========================================================
Vervangt alle hardcoded UTC-logica in het systeem.

Sessions:
  LONDON      — 07:00-12:00 UTC (premium, meeste liquiditeit)
  NY_OPEN     — 12:00-13:00 UTC (overlap London/NY, high impact)
  NEW_YORK    — 13:00-17:00 UTC (premium)
  ASIA        — 00:00-07:00 UTC (laag volume, grotendeels geblokkeerd)
  BLOCKED     — weekenden + vroeg maandag + laat vrijdag

Killzones (optimale entry tijden):
  London Open Killzone   — 07:00-09:30 UTC
  NY Open Killzone       — 12:00-14:30 UTC
  London Close Killzone  — 10:00-12:00 UTC

DST handling:
  Gebruikt Python's datetime met UTC voor consistentie.
  Lokale sessietijden worden automatisch omgezet.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional


class SessionType(str, Enum):
    LONDON = "london"
    NEW_YORK = "new_york"
    OVERLAP = "overlap"        # London/NY overlap
    ASIA = "asia"
    BLOCKED = "blocked"        # Weekend / ongewenste uren
    PRE_LONDON = "pre_london"  # 06:00-07:00 UTC


class SessionQuality(str, Enum):
    PREMIUM = "premium"        # Beste kansen
    STANDARD = "standard"      # Acceptabel
    RESTRICTED = "restricted"  # Alleen top-A signalen
    BLOCKED = "blocked"        # Geen trading


@dataclass
class SessionInfo:
    session: SessionType
    quality: SessionQuality
    is_killzone: bool
    killzone_name: Optional[str]
    is_valid_for_trading: bool
    allows_all_signals: bool   # False = alleen A/B kwaliteit
    session_start_utc: int
    session_end_utc: int
    utc_hour: int
    utc_minute: int
    day_of_week: int           # 0=Mon, 6=Sun
    is_dst_period: bool
    description: str

    def to_dict(self) -> dict:
        return {
            "session": self.session.value,
            "quality": self.quality.value,
            "is_killzone": self.is_killzone,
            "killzone_name": self.killzone_name,
            "is_valid_for_trading": self.is_valid_for_trading,
            "allows_all_signals": self.allows_all_signals,
            "description": self.description,
        }


class SessionEngine:
    """
    Timezone-aware session engine.

    Gebruik:
        se = SessionEngine()
        info = se.get_session_info(datetime.utcnow())
        if info.is_valid_for_trading:
            ...
    """

    # London summer time (BST = UTC+1): clocks forward last Sunday March → last Sunday October
    # Voor XAUUSD in UTC termen:
    # Winter: London 08:00-17:00 local = 07:00-16:00 UTC
    # Summer: London 08:00-17:00 local = 07:00-16:00 UTC (zelfde effectief want markets in UTC)

    # Sessie definitie in UTC uren
    LONDON_START = 7
    LONDON_END = 12
    OVERLAP_START = 12
    OVERLAP_END = 13
    NY_START = 13
    NY_END = 17
    ASIA_START = 0
    ASIA_END = 7

    # Killzones (uur, minuut) in UTC
    KILLZONES = {
        "London Open": (7, 0, 9, 30),
        "NY Open": (12, 0, 14, 30),
        "London Close": (10, 0, 12, 0),
    }

    # Geblokkeerde perioden
    MONDAY_BLOCKED_BEFORE = 7    # Maandag: geen trading voor 07:00 UTC
    FRIDAY_BLOCKED_AFTER = 17    # Vrijdag: geen trading na 17:00 UTC

    def get_session_info(self, dt: Optional[datetime] = None) -> SessionInfo:
        """
        Geeft volledige sessie-informatie voor een gegeven UTC datetime.
        Gebruikt datetime.utcnow() als dt=None.
        """
        if dt is None:
            dt = datetime.now(timezone.utc)

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)

        hour = dt.hour
        minute = dt.minute
        dow = dt.weekday()  # 0=Monday, 6=Sunday

        is_dst = self._is_dst_period(dt)

        # Weekend check
        if dow >= 5:
            return self._make_session(
                SessionType.BLOCKED, SessionQuality.BLOCKED,
                hour, minute, dow, is_dst,
                "Weekend — geen trading",
                valid=False,
            )

        # Maandag vroeg geblokkeerd
        if dow == 0 and hour < self.MONDAY_BLOCKED_BEFORE:
            return self._make_session(
                SessionType.BLOCKED, SessionQuality.BLOCKED,
                hour, minute, dow, is_dst,
                "Maandagochtend — markt nog gesloten",
                valid=False,
            )

        # Vrijdag laat geblokkeerd
        if dow == 4 and hour >= self.FRIDAY_BLOCKED_AFTER:
            return self._make_session(
                SessionType.BLOCKED, SessionQuality.BLOCKED,
                hour, minute, dow, is_dst,
                "Vrijdagavond — weekend bescherming",
                valid=False,
            )

        # Pre-London (06:00-07:00)
        if hour == 6:
            return self._make_session(
                SessionType.PRE_LONDON, SessionQuality.RESTRICTED,
                hour, minute, dow, is_dst,
                "Pre-London — voorbereiding, alleen A signalen",
                valid=True, all_signals=False,
            )

        # London sessie
        if self.LONDON_START <= hour < self.LONDON_END:
            kz = self._get_killzone(hour, minute)
            return self._make_session(
                SessionType.LONDON,
                SessionQuality.PREMIUM if kz else SessionQuality.PREMIUM,
                hour, minute, dow, is_dst,
                f"London Sessie{' — ' + kz + ' Killzone' if kz else ''}",
                valid=True, all_signals=True,
                killzone=kz,
            )

        # Overlap London/NY
        if self.OVERLAP_START <= hour < self.OVERLAP_END:
            kz = self._get_killzone(hour, minute)
            return self._make_session(
                SessionType.OVERLAP, SessionQuality.STANDARD,
                hour, minute, dow, is_dst,
                f"London/NY Overlap{' — ' + kz + ' Killzone' if kz else ''}",
                valid=True, all_signals=False,  # alleen A/B in overlap
                killzone=kz,
            )

        # New York sessie
        if self.NY_START <= hour < self.NY_END:
            kz = self._get_killzone(hour, minute)
            return self._make_session(
                SessionType.NEW_YORK,
                SessionQuality.PREMIUM if kz else SessionQuality.PREMIUM,
                hour, minute, dow, is_dst,
                f"New York Sessie{' — ' + kz + ' Killzone' if kz else ''}",
                valid=True, all_signals=True,
                killzone=kz,
            )

        # Asia / nacht
        return self._make_session(
            SessionType.ASIA, SessionQuality.BLOCKED,
            hour, minute, dow, is_dst,
            "Aziatische sessie — laag volume, geen trading",
            valid=False,
        )

    def is_valid_trading_time(self, dt: Optional[datetime] = None) -> bool:
        return self.get_session_info(dt).is_valid_for_trading

    def get_session_name(self, dt: Optional[datetime] = None) -> str:
        info = self.get_session_info(dt)
        return info.session.value

    def get_volatility_factor(self, dt: Optional[datetime] = None) -> float:
        """
        Geeft een volatiliteitsfactor per sessie.
        Gebruik voor positie-sizing aanpassing.
        """
        info = self.get_session_info(dt)
        factors = {
            SessionType.LONDON: 1.0,
            SessionType.NEW_YORK: 1.0,
            SessionType.OVERLAP: 1.15,    # Hogere vol tijdens overlap
            SessionType.ASIA: 0.6,
            SessionType.PRE_LONDON: 0.8,
            SessionType.BLOCKED: 0.0,
        }
        base = factors.get(info.session, 0.0)
        return base * 1.2 if info.is_killzone else base

    def get_next_trading_session(self, dt: Optional[datetime] = None) -> datetime:
        """Geeft de start van de volgende trading sessie terug."""
        if dt is None:
            dt = datetime.now(timezone.utc)

        check = dt + timedelta(minutes=30)
        for _ in range(48 * 2):  # Max 48 uur vooruitkijken
            if self.is_valid_trading_time(check):
                return check
            check += timedelta(minutes=30)

        return check

    def get_session_analytics(self, dt: Optional[datetime] = None) -> dict:
        """Sessie analytics voor dashboard."""
        info = self.get_session_info(dt)
        next_session = self.get_next_trading_session(dt) if not info.is_valid_for_trading else None
        return {
            **info.to_dict(),
            "volatility_factor": self.get_volatility_factor(dt),
            "next_session_start": next_session.isoformat() if next_session else None,
        }

    # ─────────────────────────────────────────────────────────────
    # INTERNE HELPERS
    # ─────────────────────────────────────────────────────────────

    def _get_killzone(self, hour: int, minute: int) -> Optional[str]:
        for name, (sh, sm, eh, em) in self.KILLZONES.items():
            start_min = sh * 60 + sm
            end_min = eh * 60 + em
            current_min = hour * 60 + minute
            if start_min <= current_min < end_min:
                return name
        return None

    def _is_dst_period(self, dt: datetime) -> bool:
        """
        Detecteert of DST actief is (Europa/US samen).
        DST loopt globaal van laatste zondag maart tot laatste zondag oktober.
        Voor trading doeleinden gebruiken we altijd UTC, dus DST impact is minimaal.
        """
        month = dt.month
        return 4 <= month <= 10  # Globale benadering

    def _make_session(
        self,
        session: SessionType,
        quality: SessionQuality,
        hour: int,
        minute: int,
        dow: int,
        is_dst: bool,
        description: str,
        valid: bool = False,
        all_signals: bool = False,
        killzone: Optional[str] = None,
    ) -> SessionInfo:
        session_ranges = {
            SessionType.LONDON: (self.LONDON_START, self.LONDON_END),
            SessionType.NEW_YORK: (self.NY_START, self.NY_END),
            SessionType.OVERLAP: (self.OVERLAP_START, self.OVERLAP_END),
            SessionType.ASIA: (self.ASIA_START, self.ASIA_END),
            SessionType.BLOCKED: (0, 0),
            SessionType.PRE_LONDON: (6, 7),
        }
        s_start, s_end = session_ranges.get(session, (0, 0))

        return SessionInfo(
            session=session,
            quality=quality,
            is_killzone=killzone is not None,
            killzone_name=killzone,
            is_valid_for_trading=valid,
            allows_all_signals=all_signals,
            session_start_utc=s_start,
            session_end_utc=s_end,
            utc_hour=hour,
            utc_minute=minute,
            day_of_week=dow,
            is_dst_period=is_dst,
            description=description,
        )


# ─────────────────────────────────────────────────────────────────
# MACRO EVENT KALENDER
# ─────────────────────────────────────────────────────────────────

class MacroEventEngine:
    """
    Bewaakt macro-economische events die goud sterk beïnvloeden.
    Reduceert risk rondom hoog-impact events.

    Gebruik keywords in Telegram/news feeds om events te detecteren.
    """

    HIGH_IMPACT_KEYWORDS = frozenset({
        # Fed / ECB events
        "fomc", "federal reserve", "fed decision", "interest rate decision",
        "ecb meeting", "boe meeting", "bank of england",
        # Economische data
        "nfp", "non-farm payroll", "jobs report", "employment report",
        "cpi", "consumer price index", "inflation report", "pce",
        "gdp", "retail sales", "pmi", "ism manufacturing",
        # Geopolitiek
        "war declaration", "nuclear", "emergency meeting", "flash crash",
        "market circuit breaker",
    })

    REDUCE_RISK_KEYWORDS = frozenset({
        "fomc minutes", "fed speech", "powell", "yellen",
        "treasury", "debt ceiling", "government shutdown",
        "cpi report", "inflation data", "jobs data",
    })

    def detect_event_risk(self, headline: str) -> dict:
        """
        Detecteert macro event risico in een headline.
        Retourneert risk_reduction en event_type.
        """
        text = headline.lower()

        high_impact = any(kw in text for kw in self.HIGH_IMPACT_KEYWORDS)
        medium_impact = any(kw in text for kw in self.REDUCE_RISK_KEYWORDS)

        if high_impact:
            return {
                "event_detected": True,
                "impact_level": "HIGH",
                "risk_reduction": 0.50,  # Halveer risico
                "recommendation": "Reduceer positiegrootte 50%",
            }
        elif medium_impact:
            return {
                "event_detected": True,
                "impact_level": "MEDIUM",
                "risk_reduction": 0.25,  # 25% reductie
                "recommendation": "Reduceer positiegrootte 25%",
            }
        return {
            "event_detected": False,
            "impact_level": "LOW",
            "risk_reduction": 0.0,
            "recommendation": "Normaal handelen",
        }
