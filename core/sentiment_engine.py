"""
XAUUSD V17 Sentiment Engine — Enhanced Gold Sentiment Analysis
=============================================================
Uitbreiding van de bestaande SentimentLayer met:
  - Weighted sentiment scoring (recente nieuws weegt zwaarder)
  - Rolling sentiment gemiddelde (3-window)
  - Sentiment volatiliteit meting
  - Macro event detectie (FOMC/CPI/NFP keywords)
  - Sentiment confidence score
  - Signal booster / blocker logica
  - Sentiment cache met timestamp
  - Impact op risk modifier

Sentiment labels:
  sterk_bullish  — extreem positief voor goud (score ≥ 0.5)
  bullish        — positief voor goud (score 0.25-0.5)
  neutral        — geen duidelijke richting (score -0.25 tot 0.25)
  bearish        — negatief voor goud (score -0.5 tot -0.25)
  sterk_bearish  — extreem negatief voor goud (score ≤ -0.5)

Gebruik:
  engine = SentimentEngine()
  result = engine.get_sentiment()
  modifier = engine.get_risk_modifier("long")  # 0.5 - 1.3
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# GOLD SENTIMENT KEYWORDS
# ─────────────────────────────────────────────────────────────────

_BULLISH_GOLD = frozenset({
    # USD zwakte
    "dollar falls", "dollar weakens", "dollar drops", "dxy falls", "dollar index falls",
    "weak dollar", "dollar lower", "dollar decline", "usd weakness",
    # Fed dovish
    "rate cut", "rate cuts", "fed cut", "dovish", "pause rate", "rate pause",
    "fed holds", "lower rates", "easy monetary", "quantitative easing", "qe",
    "fed pivot", "rate reduction", "accommodative",
    # Inflatie / safe haven
    "inflation rises", "inflation higher", "cpi beats", "pce higher",
    "real yields fall", "negative real rates", "inflation fears", "stagflation",
    # Geopolitiek
    "war", "conflict", "geopolit", "crisis", "safe haven", "flight to safety",
    "uncertainty", "tension", "sanctions", "middle east", "ukraine", "russia",
    "recession fears", "recession risk", "slowdown", "bank crisis", "banking stress",
    "debt ceiling", "default risk", "economic weakness",
    # Centrale bank goud
    "central bank buying", "gold reserves", "central bank gold", "gold purchases",
    "de-dollarization", "brics gold", "gold demand", "etf inflows",
    # Markt
    "gold rally", "gold gains", "gold rises", "gold surge", "gold jumps",
    "gold breakout", "gold record", "gold high", "gold bull",
})

_BEARISH_GOLD = frozenset({
    # USD sterkte
    "dollar rises", "dollar strengthens", "dollar gains", "dxy rises",
    "dollar higher", "strong dollar", "dollar rally", "usd strength",
    # Fed hawkish
    "rate hike", "rate hikes", "hawkish", "fed hike", "tightening",
    "higher rates", "rates higher", "fed raises", "quantitative tightening", "qt",
    "restrictive", "aggressive fed",
    # Real yields stijgen
    "inflation falls", "inflation lower", "cpi miss", "deflation",
    "real yields rise", "yields higher", "10-year rises", "treasury yields",
    "bond yields", "yield surge",
    # Risk-on
    "risk on", "equities rise", "stocks rally", "s&p gains", "nasdaq gains",
    "economic growth", "strong gdp", "strong jobs", "nfp beats",
    "strong economy", "growth outlook improves", "bull market",
    # Goud negatief
    "gold falls", "gold drops", "gold plunges", "gold declines",
    "gold selloff", "gold sell off", "gold outflows", "gold pressure",
    "gold weakness", "gold lower", "gold bear", "central bank selling",
})

# Macro event keywords — hoog impact → risk reductie
_MACRO_EVENTS = frozenset({
    "fomc", "federal reserve meeting", "fed decision", "interest rate decision",
    "nfp", "non-farm payroll", "jobs report", "cpi report", "consumer price index",
    "pce inflation", "gdp report", "ecb meeting", "boe meeting",
    "bank of england", "powell speech", "fed minutes",
})

# Super high impact — blokkeer trading
_SUPER_HIGH_IMPACT = frozenset({
    "flash crash", "market halt", "circuit breaker", "emergency meeting",
    "nuclear", "market closure", "exchange halt",
})


# ─────────────────────────────────────────────────────────────────
# DATA CLASSES
# ─────────────────────────────────────────────────────────────────

@dataclass
class EnhancedSentiment:
    score: float                          # -1.0 tot +1.0
    label: str                            # sterk_bullish .. sterk_bearish
    confidence: float                     # 0.0 tot 1.0
    headline_count: int
    bullish_count: int
    bearish_count: int
    sources: list[str] = field(default_factory=list)
    rolling_avg: float = 0.0              # Gemiddelde van laatste 3 fetches
    rolling_volatility: float = 0.0       # Standaardafwijking rolling window
    macro_event_detected: bool = False
    macro_event_level: str = "LOW"        # LOW | MEDIUM | HIGH | CRITICAL
    macro_event_keywords: list[str] = field(default_factory=list)
    risk_modifier: float = 1.0            # Multiplier voor position sizing
    fetched_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 3),
            "label": self.label,
            "confidence": round(self.confidence, 3),
            "headline_count": self.headline_count,
            "bullish_count": self.bullish_count,
            "bearish_count": self.bearish_count,
            "rolling_avg": round(self.rolling_avg, 3),
            "rolling_volatility": round(self.rolling_volatility, 3),
            "macro_event_detected": self.macro_event_detected,
            "macro_event_level": self.macro_event_level,
            "macro_event_keywords": self.macro_event_keywords,
            "risk_modifier": round(self.risk_modifier, 3),
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "sources": self.sources[:5],
        }

    @property
    def is_bullish(self) -> bool:
        return self.score > 0.15

    @property
    def is_bearish(self) -> bool:
        return self.score < -0.15

    @property
    def is_strongly_bullish(self) -> bool:
        return self.score >= 0.5

    @property
    def is_strongly_bearish(self) -> bool:
        return self.score <= -0.5

    def blocks_long(self) -> bool:
        return self.is_strongly_bearish or (self.macro_event_level in ("HIGH", "CRITICAL"))

    def blocks_short(self) -> bool:
        return self.is_strongly_bullish or (self.macro_event_level in ("HIGH", "CRITICAL"))

    def boosts_long(self) -> bool:
        return self.is_bullish and not self.macro_event_detected

    def boosts_short(self) -> bool:
        return self.is_bearish and not self.macro_event_detected


class SentimentEngine:
    """
    Enhanced Sentiment Engine voor XAUUSD V17.

    Features:
      - 30-minuten cache
      - Rolling 3-window gemiddelde
      - Sentiment volatiliteit tracking
      - Macro event detectie
      - Risk modifier per handelsdirectie
    """

    def __init__(
        self,
        cache_minutes: int = 30,
        rolling_window: int = 3,
        symbols: list[str] = None,
    ):
        self._cache_minutes = cache_minutes
        self._rolling_window = rolling_window
        self._symbols = symbols or ["GC=F", "GLD", "XAUUSD=X"]
        self._cached: Optional[EnhancedSentiment] = None
        self._cached_at: float = 0.0
        self._history: deque[float] = deque(maxlen=rolling_window)

    def get_sentiment(self, force_refresh: bool = False) -> EnhancedSentiment:
        """
        Haalt goud sentiment op. Gebruikt cache tot cache_minutes verstreken.
        """
        age = time.time() - self._cached_at
        if not force_refresh and self._cached is not None and age < self._cache_minutes * 60:
            return self._cached

        result = self._fetch_and_score()
        self._cached = result
        self._cached_at = time.time()

        logger.info(
            "Sentiment bijgewerkt: %s (score=%.2f, conf=%.0f%%, %d headlines, macro=%s)",
            result.label, result.score, result.confidence * 100,
            result.headline_count, result.macro_event_level,
        )
        return result

    def get_risk_modifier(self, direction: str) -> float:
        """
        Geeft een risk modifier terug op basis van sentiment.

        direction: "long" | "short"

        Returns:
          1.0   = normaal
          1.15  = boost (sentiment bevestigt richting)
          1.30  = sterke boost
          0.75  = reductie (sentiment neutral maar macro event)
          0.50  = sterke reductie (macro event)
          0.0   = geblokkeerd (tegenstrijdig sentiment)
        """
        s = self.get_sentiment()

        if s.macro_event_level == "CRITICAL":
            return 0.25  # Bijna geen trading

        if s.macro_event_level == "HIGH":
            return 0.50  # Halveer risico

        if direction == "long":
            if s.blocks_long():
                return 0.0
            if s.is_strongly_bullish:
                return 1.30
            if s.boosts_long():
                return 1.15
            if s.is_bearish:
                return 0.75
        elif direction == "short":
            if s.blocks_short():
                return 0.0
            if s.is_strongly_bearish:
                return 1.30
            if s.boosts_short():
                return 1.15
            if s.is_bullish:
                return 0.75

        return 1.0

    def get_signal_filter(self, direction: str) -> dict:
        """
        Geeft filter informatie terug voor signal generation.
        """
        s = self.get_sentiment()
        modifier = self.get_risk_modifier(direction)

        return {
            "blocked": modifier == 0.0,
            "risk_modifier": modifier,
            "sentiment_score": s.score,
            "sentiment_label": s.label,
            "confidence": s.confidence,
            "macro_event": s.macro_event_detected,
            "macro_level": s.macro_event_level,
            "reason": self._get_filter_reason(direction, s, modifier),
        }

    # ─────────────────────────────────────────────────────────────
    # INTERNE METHODEN
    # ─────────────────────────────────────────────────────────────

    def _fetch_and_score(self) -> EnhancedSentiment:
        """Haalt nieuws op en berekent gewogen sentiment score."""
        try:
            import yfinance as yf
        except ImportError:
            logger.error("yfinance niet beschikbaar — neutral sentiment")
            return self._neutral()

        all_news: list[dict] = []
        for sym in self._symbols:
            try:
                ticker = yf.Ticker(sym)
                items = ticker.news or []
                all_news.extend(items)
            except Exception as e:
                logger.debug("Nieuws ophalen mislukt voor %s: %s", sym, e)

        if not all_news:
            logger.warning("Geen gold-nieuws gevonden")
            return self._neutral()

        # Dedupliceer
        seen: set[str] = set()
        unique = []
        for item in all_news:
            title = (item.get("title") or "").strip()
            if title and title not in seen:
                seen.add(title)
                unique.append(item)

        bullish = 0
        bearish = 0
        weighted_score = 0.0
        macro_keywords: list[str] = []
        headlines: list[str] = []
        super_high_detected = False

        # Gewogen scoring: recentere items wegen zwaarder
        total_items = min(len(unique), 30)
        for idx, item in enumerate(unique[:total_items]):
            title = (item.get("title") or "").lower()
            summary = (item.get("summary") or "").lower()
            text = f"{title} {summary}"
            if not title:
                continue

            headlines.append(item.get("title", "")[:100])

            # Gewicht: eerste items zijn recenter (hogere prioriteit)
            weight = 1.0 - (idx / total_items) * 0.5  # 1.0 → 0.5

            b_count = sum(1 for kw in _BULLISH_GOLD if kw in text)
            r_count = sum(1 for kw in _BEARISH_GOLD if kw in text)

            if b_count > r_count:
                bullish += 1
                weighted_score += weight
            elif r_count > b_count:
                bearish += 1
                weighted_score -= weight

            # Macro event detectie
            for kw in _MACRO_EVENTS:
                if kw in text and kw not in macro_keywords:
                    macro_keywords.append(kw)

            # Super high impact
            if any(kw in text for kw in _SUPER_HIGH_IMPACT):
                super_high_detected = True

        # Normaliseer score
        total = bullish + bearish
        raw_score = (bullish - bearish) / total if total > 0 else 0.0
        # Combineer unweighted en weighted
        w_normalized = weighted_score / total_items if total_items > 0 else 0.0
        score = round(0.6 * raw_score + 0.4 * w_normalized, 3)
        score = max(-1.0, min(1.0, score))

        # Label toekennen
        label = self._score_to_label(score)

        # Confidence: hoe meer headlines, hoe hoger de confidence
        confidence = min(0.95, total_items / 20.0 * 0.6 + abs(score) * 0.4)

        # Rolling window update
        self._history.append(score)
        rolling_avg = sum(self._history) / len(self._history)

        # Rolling volatiliteit
        if len(self._history) >= 2:
            vals = list(self._history)
            mean = sum(vals) / len(vals)
            rolling_vol = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
        else:
            rolling_vol = 0.0

        # Macro event level
        if super_high_detected:
            macro_level = "CRITICAL"
        elif len(macro_keywords) >= 3:
            macro_level = "HIGH"
        elif len(macro_keywords) >= 1:
            macro_level = "MEDIUM"
        else:
            macro_level = "LOW"

        # Risk modifier
        risk_mod = self._calc_risk_modifier(score, macro_level)

        return EnhancedSentiment(
            score=score,
            label=label,
            confidence=round(confidence, 3),
            headline_count=len(headlines),
            bullish_count=bullish,
            bearish_count=bearish,
            sources=headlines[:6],
            rolling_avg=round(rolling_avg, 3),
            rolling_volatility=round(rolling_vol, 3),
            macro_event_detected=len(macro_keywords) > 0,
            macro_event_level=macro_level,
            macro_event_keywords=macro_keywords[:5],
            risk_modifier=risk_mod,
            fetched_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _score_to_label(score: float) -> str:
        if score >= 0.5:    return "sterk_bullish"
        if score >= 0.25:   return "bullish"
        if score <= -0.5:   return "sterk_bearish"
        if score <= -0.25:  return "bearish"
        return "neutral"

    @staticmethod
    def _calc_risk_modifier(score: float, macro_level: str) -> float:
        if macro_level == "CRITICAL":   return 0.25
        if macro_level == "HIGH":       return 0.50
        if macro_level == "MEDIUM":     return 0.75
        if abs(score) >= 0.5:           return 1.20
        if abs(score) >= 0.25:          return 1.10
        return 1.0

    @staticmethod
    def _neutral() -> EnhancedSentiment:
        return EnhancedSentiment(
            score=0.0, label="neutral", confidence=0.0,
            headline_count=0, bullish_count=0, bearish_count=0,
            fetched_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _get_filter_reason(direction: str, s: EnhancedSentiment, modifier: float) -> str:
        if modifier == 0.0:
            return f"Geblokkeerd: {s.label} sentiment vs {direction} richting"
        if s.macro_event_detected:
            return f"Macro event ({s.macro_event_level}): risk gereduceerd naar {modifier:.0%}"
        if modifier > 1.0:
            return f"Sentiment boost: {s.label} bevestigt {direction} ({modifier:.0%})"
        if modifier < 1.0:
            return f"Sentiment tegenwerking: {s.label} vs {direction} ({modifier:.0%})"
        return "Sentiment neutraal — normaal handelen"
