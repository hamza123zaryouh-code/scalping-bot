from __future__ import annotations

import logging
import time

import yfinance as yf

from .models import SentimentScore

logger = logging.getLogger(__name__)

# XAUUSD/Gold-specifieke drivers — wat drijft goudprijzen omhoog
_BULLISH_GOLD = frozenset({
    # USD zwakte
    "dollar falls", "dollar weakens", "dollar drops", "dxy falls", "dollar index falls",
    "weak dollar", "dollar lower",
    # Fed dovish / renteverlagingen
    "rate cut", "rate cuts", "fed cut", "dovish", "pause rate", "rate pause",
    "fed holds", "lower rates", "easy monetary", "quantitative easing",
    # Inflatie / real yields
    "inflation rises", "inflation higher", "cpi beats", "pce higher",
    "real yields fall", "negative real rates", "inflation fears",
    # Geopolitiek / vlucht naar veiligheid
    "war", "conflict", "geopolit", "crisis", "safe haven", "flight to safety",
    "uncertainty", "tension", "sanctions", "middle east", "ukraine",
    "recession fears", "recession risk", "slowdown", "stagflation",
    # Centrale bank goudaankopen
    "central bank buying", "gold reserves", "central bank gold", "gold purchases",
    "de-dollarization", "brics gold",
    # Marktsentiment
    "gold rally", "gold gains", "gold rises", "gold surge", "gold jumps",
    "gold demand", "gold etf inflows", "gld inflows", "physical gold demand",
    "gold breakout", "gold record", "gold high",
    # Economische zwakte
    "bank crisis", "banking stress", "debt ceiling", "default risk",
    "economic weakness", "job losses",
})

# Wat duwt goudprijzen omlaag
_BEARISH_GOLD = frozenset({
    # USD sterkte
    "dollar rises", "dollar strengthens", "dollar gains", "dxy rises",
    "dollar higher", "strong dollar", "dollar rally",
    # Fed hawkish / renteverhogingen
    "rate hike", "rate hikes", "hawkish", "fed hike", "tightening",
    "higher rates", "rates higher", "fed raises",
    # Inflatie daalt / real yields stijgen
    "inflation falls", "inflation lower", "cpi miss", "deflation",
    "real yields rise", "yields higher", "10-year rises", "treasury yields",
    # Risk-on / vlucht uit goud
    "risk on", "equities rise", "stocks rally", "s&p gains", "nasdaq gains",
    "economic growth", "strong gdp", "strong jobs", "nfp beats",
    "strong economy", "growth outlook improves",
    # Goudspecifiek negatief
    "gold falls", "gold drops", "gold plunges", "gold declines",
    "gold selloff", "gold sell off", "gold outflows", "gld outflows",
    "gold pressure", "gold weakness", "gold lower",
    # Centrale bank verkopen
    "central bank selling", "imf gold sales",
})


class SentimentLayer:
    """
    Haalt XAUUSD/gold-relevant nieuws op via yfinance en scoort het
    op basis van gold-specifieke drijvers (DXY, Fed, inflatie, geopolitiek).
    """

    def __init__(self, symbol: str = "GC=F", cache_minutes: int = 30) -> None:
        self.symbol = symbol
        self.cache_minutes = cache_minutes
        self._cached: SentimentScore | None = None
        self._cached_at: float = 0.0

    def get_sentiment(self) -> SentimentScore:
        age = time.time() - self._cached_at
        if self._cached is not None and age < self.cache_minutes * 60:
            return self._cached
        result = self._fetch_and_score()
        self._cached = result
        self._cached_at = time.time()
        logger.info(
            "Gold sentiment bijgewerkt: %s (score=%.2f, %d headlines)",
            result.label, result.score, result.headline_count,
        )
        return result

    def _fetch_and_score(self) -> SentimentScore:
        # Haal nieuws op voor zowel GC=F (gold futures) als gerelateerde tickers
        all_news: list[dict] = []
        for ticker_sym in [self.symbol, "GLD", "XAUUSD=X"]:
            try:
                ticker = yf.Ticker(ticker_sym)
                items = ticker.news or []
                all_news.extend(items)
            except Exception:
                pass

        if not all_news:
            logger.warning("Geen gold-nieuws gevonden voor sentiment scoring")
            return SentimentScore(score=0.0, label="neutral", headline_count=0)

        # Dedupliceer op titel
        seen: set[str] = set()
        unique_news = []
        for item in all_news:
            title = (item.get("title") or "").strip()
            if title and title not in seen:
                seen.add(title)
                unique_news.append(item)

        bullish = 0
        bearish = 0
        headlines: list[str] = []

        for item in unique_news[:30]:
            title = (item.get("title") or "").lower()
            summary = (item.get("summary") or "").lower()
            text = f"{title} {summary}"
            if not title:
                continue
            headlines.append(item.get("title", "")[:100])

            b = sum(1 for kw in _BULLISH_GOLD if kw in text)
            r = sum(1 for kw in _BEARISH_GOLD if kw in text)

            if b > r:
                bullish += 1
            elif r > b:
                bearish += 1

        total = bullish + bearish
        raw = (bullish - bearish) / total if total > 0 else 0.0

        # Drempel: 0.25 = zwakke bias, 0.5 = sterke bias (filtert signalen)
        if raw >= 0.5:
            label = "sterk_bullish"
        elif raw >= 0.25:
            label = "bullish"
        elif raw <= -0.5:
            label = "sterk_bearish"
        elif raw <= -0.25:
            label = "bearish"
        else:
            label = "neutral"

        return SentimentScore(
            score=round(raw, 3),
            label=label,
            headline_count=len(headlines),
            sources=headlines[:6],
        )
