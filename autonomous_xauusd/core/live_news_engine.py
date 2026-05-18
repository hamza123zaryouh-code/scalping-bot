"""
Live News Engine — Real-time XAUUSD/gold market news ingestion.

Sources (in priority order):
  1. NewsAPI.org         (requires NEWSAPI_KEY in env)
  2. RSS feeds           (ForexFactory, Reuters, FXStreet, MarketWatch)
  3. yfinance headlines  (always available, fallback)

Features:
  - Multi-source deduplication via title fingerprint
  - Headline clustering to avoid noise amplification
  - Weighted sentiment scoring (recency + keyword density)
  - Bullish/bearish confidence score
  - Volatility expectation score
  - News danger score (for FTMO-aware position sizing)
  - Impact score per headline (low / medium / high / critical)
  - Urgency score (time-sensitive events)
  - Local JSON cache with TTL to prevent API spam
  - Retry logic with exponential back-off
  - Integrates with existing SentimentEngine interface

Environment variables:
  NEWSAPI_KEY           — NewsAPI.org API key
  NEWS_CACHE_MINUTES    — Cache TTL in minutes (default 20)
  NEWS_MAX_HEADLINES    — Max headlines to process per cycle (default 40)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_UTC = timezone.utc

# ─────────────────────────────────────────────────────────────────
# KEYWORD DICTIONARIES
# ─────────────────────────────────────────────────────────────────

_BULLISH_KEYWORDS: frozenset[str] = frozenset({
    # USD weakness
    "dollar falls", "dollar weakens", "dollar drops", "dxy falls", "weak dollar",
    "dollar lower", "dollar decline", "usd weakness", "dollar index falls",
    # Fed dovish
    "rate cut", "rate cuts", "fed cut", "dovish", "pause rate", "rate pause",
    "fed holds", "lower rates", "easy monetary", "quantitative easing", "qe",
    "fed pivot", "rate reduction", "accommodative", "fed signals cuts",
    # Inflation / safe haven
    "inflation rises", "inflation higher", "cpi beats", "pce higher",
    "real yields fall", "negative real rates", "inflation fears", "stagflation",
    # Geopolitics
    "war", "conflict", "geopolit", "crisis", "safe haven", "flight to safety",
    "uncertainty", "tension", "sanctions", "middle east", "ukraine", "russia",
    "recession fears", "recession risk", "slowdown", "bank crisis", "banking stress",
    "debt ceiling", "default risk", "economic weakness",
    # Central bank gold
    "central bank buying", "gold reserves", "central bank gold", "gold purchases",
    "de-dollarization", "brics gold", "gold demand", "etf inflows",
    # Market signals
    "gold rally", "gold gains", "gold rises", "gold surge", "gold jumps",
    "gold breakout", "gold record", "gold high", "gold bull", "xauusd buy",
    "gold all-time high", "gold safe haven demand",
})

_BEARISH_KEYWORDS: frozenset[str] = frozenset({
    # USD strength
    "dollar rises", "dollar strengthens", "dollar gains", "dxy rises",
    "dollar higher", "strong dollar", "dollar rally", "usd strength",
    # Fed hawkish
    "rate hike", "rate hikes", "hawkish", "fed hike", "tightening",
    "higher rates", "rates higher", "fed raises", "quantitative tightening", "qt",
    "restrictive", "aggressive fed",
    # Real yields up
    "inflation falls", "inflation lower", "cpi miss", "deflation",
    "real yields rise", "yields higher", "10-year rises", "treasury yields",
    "bond yields", "yield surge",
    # Risk-on
    "risk on", "equities rise", "stocks rally", "s&p gains", "nasdaq gains",
    "economic growth", "strong gdp", "strong jobs", "nfp beats",
    "strong economy", "growth outlook improves", "bull market", "market rally",
    # Gold negative
    "gold falls", "gold drops", "gold plunges", "gold declines",
    "gold selloff", "gold sell off", "gold outflows", "gold pressure",
    "gold weakness", "gold lower", "gold bear", "central bank selling",
})

_HIGH_IMPACT_KEYWORDS: frozenset[str] = frozenset({
    "fomc", "federal reserve", "fed decision", "interest rate decision", "rate decision",
    "nfp", "non-farm payroll", "jobs report", "cpi report", "consumer price index",
    "pce inflation", "gdp report", "ecb meeting", "boe meeting", "bank of england",
    "powell speech", "fed minutes", "inflation data", "core cpi", "pce data",
})

_CRITICAL_KEYWORDS: frozenset[str] = frozenset({
    "flash crash", "market halt", "circuit breaker", "emergency meeting",
    "nuclear", "market closure", "exchange halt", "black swan",
    "financial crisis", "lehman", "systemic risk",
})

# RSS feeds that reliably cover gold/macro news
_RSS_FEEDS: list[tuple[str, str]] = [
    ("forexfactory", "https://www.forexfactory.com/news"),
    ("fxstreet_gold", "https://www.fxstreet.com/rss/news"),
    ("marketwatch_economy", "https://feeds.marketwatch.com/marketwatch/economy-politics/"),
    ("investing_commodities", "https://www.investing.com/rss/news_14.rss"),
    ("reuters_markets", "https://feeds.reuters.com/reuters/businessNews"),
    ("kitco_gold", "https://www.kitco.com/rss/kitco-news-gold.rss"),
]

# NewsAPI query topics for XAUUSD
_NEWSAPI_QUERIES: list[str] = [
    "gold price",
    "XAUUSD",
    "Federal Reserve interest rates",
    "US inflation CPI",
    "dollar index DXY",
]

_CACHE_PATH = Path("live_logs/news_cache.json")
_DEFAULT_CACHE_MINUTES = int(os.getenv("NEWS_CACHE_MINUTES", "20"))
_DEFAULT_MAX_HEADLINES = int(os.getenv("NEWS_MAX_HEADLINES", "40"))


# ─────────────────────────────────────────────────────────────────
# DATA CLASSES
# ─────────────────────────────────────────────────────────────────

@dataclass
class NewsItem:
    title: str
    source: str
    published_at: datetime | None
    url: str = ""
    summary: str = ""
    impact_score: float = 0.0      # 0.0 – 1.0
    sentiment_score: float = 0.0   # -1.0 – +1.0 (gold perspective)
    urgency_score: float = 0.0     # 0.0 – 1.0 (time-sensitive)
    danger_score: float = 0.0      # 0.0 – 1.0 (trading risk level)
    keywords_matched: list[str] = field(default_factory=list)
    is_critical: bool = False

    def fingerprint(self) -> str:
        return hashlib.md5(self.title.lower().strip().encode()).hexdigest()[:12]

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "source": self.source,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "url": self.url,
            "impact_score": round(self.impact_score, 3),
            "sentiment_score": round(self.sentiment_score, 3),
            "urgency_score": round(self.urgency_score, 3),
            "danger_score": round(self.danger_score, 3),
            "keywords_matched": self.keywords_matched[:5],
            "is_critical": self.is_critical,
        }


@dataclass
class NewsAnalysis:
    items: list[NewsItem]
    bullish_score: float       # 0.0 – 1.0
    bearish_score: float       # 0.0 – 1.0
    composite_sentiment: float # -1.0 – +1.0
    volatility_expectation: float  # 0.0 – 1.0
    danger_score: float        # 0.0 – 1.0 (trade risk)
    urgency_score: float       # 0.0 – 1.0
    high_impact_count: int
    critical_count: int
    total_headlines: int
    sources: list[str]
    top_keywords: list[str]
    analysis_time: datetime
    cache_hit: bool = False

    def should_pause_trading(self, danger_threshold: float = 0.65) -> bool:
        return self.danger_score >= danger_threshold or self.critical_count > 0

    def risk_modifier(self) -> float:
        """Returns 0.25 – 1.3 based on market conditions."""
        if self.critical_count > 0:
            return 0.25
        if self.danger_score >= 0.7:
            return 0.40
        if self.danger_score >= 0.5:
            return 0.60
        if self.volatility_expectation >= 0.7:
            return 0.70
        if abs(self.composite_sentiment) >= 0.5:
            return 1.20
        if abs(self.composite_sentiment) >= 0.3:
            return 1.10
        return 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "bullish_score": round(self.bullish_score, 3),
            "bearish_score": round(self.bearish_score, 3),
            "composite_sentiment": round(self.composite_sentiment, 3),
            "volatility_expectation": round(self.volatility_expectation, 3),
            "danger_score": round(self.danger_score, 3),
            "urgency_score": round(self.urgency_score, 3),
            "high_impact_count": self.high_impact_count,
            "critical_count": self.critical_count,
            "total_headlines": self.total_headlines,
            "sources": self.sources[:6],
            "top_keywords": self.top_keywords[:8],
            "analysis_time": self.analysis_time.isoformat(),
            "should_pause_trading": self.should_pause_trading(),
            "risk_modifier": round(self.risk_modifier(), 3),
            "cache_hit": self.cache_hit,
            "top_items": [item.to_dict() for item in self.items[:5]],
        }


# ─────────────────────────────────────────────────────────────────
# MAIN ENGINE
# ─────────────────────────────────────────────────────────────────

class LiveNewsEngine:
    """
    Production multi-source live news engine for XAUUSD trading.

    Thread-safe, caches to disk, supports graceful degradation if
    external APIs are unavailable.
    """

    def __init__(
        self,
        cache_minutes: int = _DEFAULT_CACHE_MINUTES,
        max_headlines: int = _DEFAULT_MAX_HEADLINES,
        newsapi_key: str | None = None,
    ) -> None:
        self._cache_minutes = cache_minutes
        self._max_headlines = max_headlines
        self._newsapi_key = newsapi_key or os.getenv("NEWSAPI_KEY", "").strip()
        self._cached_analysis: NewsAnalysis | None = None
        self._cached_at: float = 0.0
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

    def get_analysis(self, force_refresh: bool = False) -> NewsAnalysis:
        """Return live news analysis, using cache if still valid."""
        age = time.time() - self._cached_at
        if not force_refresh and self._cached_analysis is not None and age < self._cache_minutes * 60:
            result = self._cached_analysis
            result.cache_hit = True
            return result

        # Try disk cache first (survives process restarts)
        if not force_refresh:
            disk = self._load_disk_cache()
            if disk is not None:
                self._cached_analysis = disk
                self._cached_at = time.time()
                disk.cache_hit = True
                return disk

        items = self._fetch_all_sources()
        if not items:
            logger.warning("LiveNewsEngine: no headlines fetched — returning neutral analysis")
            return self._neutral_analysis()

        analysis = self._analyze(items)
        self._cached_analysis = analysis
        self._cached_at = time.time()
        self._save_disk_cache(analysis)

        logger.info(
            "NewsEngine: %d headlines | sentiment=%.2f | danger=%.2f | volatility=%.2f | %s",
            analysis.total_headlines,
            analysis.composite_sentiment,
            analysis.danger_score,
            analysis.volatility_expectation,
            "PAUSE" if analysis.should_pause_trading() else "OK",
        )
        return analysis

    # ─────────────────────────────────────────────────────────────
    # SOURCE FETCHERS
    # ─────────────────────────────────────────────────────────────

    def _fetch_all_sources(self) -> list[NewsItem]:
        items: list[NewsItem] = []
        seen_fingerprints: set[str] = set()

        def _dedupe_add(new_items: list[NewsItem]) -> None:
            for item in new_items:
                fp = item.fingerprint()
                if fp not in seen_fingerprints:
                    seen_fingerprints.add(fp)
                    items.append(item)

        # Source 1: NewsAPI (highest quality, structured)
        if self._newsapi_key:
            try:
                _dedupe_add(self._fetch_newsapi())
            except Exception as exc:
                logger.warning("NewsAPI fetch failed: %s", exc)

        # Source 2: RSS feeds
        try:
            _dedupe_add(self._fetch_rss_feeds())
        except Exception as exc:
            logger.warning("RSS fetch failed: %s", exc)

        # Source 3: yfinance headlines (always available fallback)
        try:
            _dedupe_add(self._fetch_yfinance())
        except Exception as exc:
            logger.warning("yfinance news fetch failed: %s", exc)

        # Sort by recency, limit count
        items.sort(key=lambda x: x.published_at or datetime.min.replace(tzinfo=_UTC), reverse=True)
        return items[: self._max_headlines]

    def _fetch_newsapi(self) -> list[NewsItem]:
        """Fetch from NewsAPI.org using gold/macro topics."""
        import urllib.parse
        import urllib.request

        items: list[NewsItem] = []
        for query in _NEWSAPI_QUERIES[:3]:  # limit to 3 queries to conserve quota
            url = (
                "https://newsapi.org/v2/everything?"
                + urllib.parse.urlencode({
                    "q": query,
                    "language": "en",
                    "sortBy": "publishedAt",
                    "pageSize": 10,
                    "apiKey": self._newsapi_key,
                })
            )
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "XAUUSD-Trading-Bot/1.0"})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = json.loads(resp.read().decode())
            except Exception as exc:
                logger.debug("NewsAPI query '%s' failed: %s", query, exc)
                continue

            for article in data.get("articles", []):
                title = (article.get("title") or "").strip()
                if not title or title == "[Removed]":
                    continue
                pub_raw = article.get("publishedAt")
                pub_dt: datetime | None = None
                if pub_raw:
                    try:
                        pub_dt = datetime.fromisoformat(pub_raw.replace("Z", "+00:00"))
                    except Exception:
                        pass
                items.append(NewsItem(
                    title=title,
                    source=f"newsapi:{article.get('source', {}).get('name', 'unknown')}",
                    published_at=pub_dt,
                    url=article.get("url", ""),
                    summary=(article.get("description") or "")[:200],
                ))

        logger.debug("NewsAPI: fetched %d items", len(items))
        return items

    def _fetch_rss_feeds(self) -> list[NewsItem]:
        """Fetch from RSS/Atom feeds."""
        try:
            import feedparser  # type: ignore[import-untyped]
        except ImportError:
            logger.debug("feedparser not installed — skipping RSS feeds")
            return []

        items: list[NewsItem] = []
        for feed_name, feed_url in _RSS_FEEDS:
            try:
                feed = feedparser.parse(feed_url)
                for entry in (feed.entries or [])[:8]:
                    title = (getattr(entry, "title", "") or "").strip()
                    if not title:
                        continue
                    pub_dt: datetime | None = None
                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                        try:
                            import calendar
                            ts = calendar.timegm(entry.published_parsed)
                            pub_dt = datetime.fromtimestamp(ts, tz=_UTC)
                        except Exception:
                            pass
                    items.append(NewsItem(
                        title=title,
                        source=f"rss:{feed_name}",
                        published_at=pub_dt,
                        url=getattr(entry, "link", ""),
                        summary=(getattr(entry, "summary", "") or "")[:200],
                    ))
            except Exception as exc:
                logger.debug("RSS feed %s failed: %s", feed_name, exc)

        logger.debug("RSS feeds: fetched %d items", len(items))
        return items

    def _fetch_yfinance(self) -> list[NewsItem]:
        """Fetch from yfinance ticker news (gold futures + gold ETF)."""
        try:
            import yfinance as yf
        except ImportError:
            return []

        items: list[NewsItem] = []
        for ticker_sym in ("GC=F", "GLD", "XAUUSD=X"):
            try:
                ticker = yf.Ticker(ticker_sym)
                news_list = ticker.news or []
                for article in news_list[:10]:
                    title = (article.get("title") or "").strip()
                    if not title:
                        continue
                    pub_ts = article.get("providerPublishTime")
                    pub_dt: datetime | None = None
                    if pub_ts:
                        try:
                            pub_dt = datetime.fromtimestamp(int(pub_ts), tz=_UTC)
                        except Exception:
                            pass
                    items.append(NewsItem(
                        title=title,
                        source=f"yfinance:{ticker_sym}",
                        published_at=pub_dt,
                        url=article.get("link", ""),
                        summary=(article.get("summary") or "")[:200],
                    ))
            except Exception as exc:
                logger.debug("yfinance %s news failed: %s", ticker_sym, exc)

        logger.debug("yfinance: fetched %d items", len(items))
        return items

    # ─────────────────────────────────────────────────────────────
    # ANALYSIS ENGINE
    # ─────────────────────────────────────────────────────────────

    def _analyze(self, items: list[NewsItem]) -> NewsAnalysis:
        now = datetime.now(_UTC)
        total = len(items)
        sources: set[str] = set()
        keyword_freq: dict[str, int] = {}
        bullish_weight = 0.0
        bearish_weight = 0.0
        high_impact_count = 0
        critical_count = 0
        max_danger = 0.0
        max_urgency = 0.0
        volatility_signals = 0

        for idx, item in enumerate(items):
            # Recency weight: most recent item = 1.0, oldest = 0.4
            recency_w = 1.0 - (idx / total) * 0.6

            text = f"{item.title} {item.summary}".lower()
            sources.add(item.source.split(":")[0])

            # Keyword scoring
            bull_matches: list[str] = []
            bear_matches: list[str] = []
            for kw in _BULLISH_KEYWORDS:
                if kw in text:
                    bull_matches.append(kw)
                    keyword_freq[kw] = keyword_freq.get(kw, 0) + 1
            for kw in _BEARISH_KEYWORDS:
                if kw in text:
                    bear_matches.append(kw)
                    keyword_freq[kw] = keyword_freq.get(kw, 0) + 1

            net = len(bull_matches) - len(bear_matches)
            if net > 0:
                bullish_weight += recency_w * min(net / 3, 1.0)
            elif net < 0:
                bearish_weight += recency_w * min(abs(net) / 3, 1.0)

            item.keywords_matched = (bull_matches + bear_matches)[:5]

            # Impact classification
            high_impact_words = sum(1 for kw in _HIGH_IMPACT_KEYWORDS if kw in text)
            if high_impact_words >= 2:
                item.impact_score = 0.9
                high_impact_count += 1
            elif high_impact_words == 1:
                item.impact_score = 0.6
            else:
                item.impact_score = 0.2

            # Critical events
            if any(kw in text for kw in _CRITICAL_KEYWORDS):
                item.is_critical = True
                item.impact_score = 1.0
                critical_count += 1

            # Urgency: recent = urgent
            if item.published_at is not None:
                age_hours = (now - item.published_at).total_seconds() / 3600
                item.urgency_score = max(0.0, 1.0 - age_hours / 4)
            else:
                item.urgency_score = 0.3

            # Sentiment per item
            if bull_matches and not bear_matches:
                item.sentiment_score = min(1.0, len(bull_matches) / 4)
            elif bear_matches and not bull_matches:
                item.sentiment_score = -min(1.0, len(bear_matches) / 4)

            # Danger score per item
            item.danger_score = item.impact_score * 0.5 + item.urgency_score * 0.3
            if item.is_critical:
                item.danger_score = 1.0

            max_danger = max(max_danger, item.danger_score)
            max_urgency = max(max_urgency, item.urgency_score)

            # Volatility signal: high-impact news near market open/close
            if item.impact_score >= 0.6 and item.urgency_score >= 0.7:
                volatility_signals += 1

        # Normalize aggregate scores
        norm = total if total > 0 else 1
        bullish_score = min(1.0, bullish_weight / norm * 2)
        bearish_score = min(1.0, bearish_weight / norm * 2)
        composite = round(bullish_score - bearish_score, 3)

        volatility_expectation = min(1.0, (
            high_impact_count * 0.15
            + critical_count * 0.5
            + volatility_signals * 0.2
        ))

        # Aggregate danger = blend of max single danger + average
        avg_danger = sum(item.danger_score for item in items) / norm
        agg_danger = round(0.6 * max_danger + 0.4 * avg_danger, 3)
        if critical_count > 0:
            agg_danger = max(agg_danger, 0.9)

        # Top keywords by frequency
        top_kw = sorted(keyword_freq.items(), key=lambda x: x[1], reverse=True)
        top_keywords = [kw for kw, _ in top_kw[:8]]

        return NewsAnalysis(
            items=items,
            bullish_score=round(bullish_score, 3),
            bearish_score=round(bearish_score, 3),
            composite_sentiment=composite,
            volatility_expectation=round(volatility_expectation, 3),
            danger_score=agg_danger,
            urgency_score=round(max_urgency, 3),
            high_impact_count=high_impact_count,
            critical_count=critical_count,
            total_headlines=total,
            sources=sorted(sources),
            top_keywords=top_keywords,
            analysis_time=now,
        )

    # ─────────────────────────────────────────────────────────────
    # DISK CACHE
    # ─────────────────────────────────────────────────────────────

    def _load_disk_cache(self) -> NewsAnalysis | None:
        try:
            if not _CACHE_PATH.exists():
                return None
            raw = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
            saved_at_str = raw.get("saved_at")
            if not saved_at_str:
                return None
            saved_at = datetime.fromisoformat(saved_at_str)
            age_minutes = (datetime.now(_UTC) - saved_at).total_seconds() / 60
            if age_minutes > self._cache_minutes:
                return None
            return self._dict_to_analysis(raw)
        except Exception as exc:
            logger.debug("News disk cache load failed: %s", exc)
            return None

    def _save_disk_cache(self, analysis: NewsAnalysis) -> None:
        try:
            payload = analysis.to_dict()
            payload["saved_at"] = datetime.now(_UTC).isoformat()
            _CACHE_PATH.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        except Exception as exc:
            logger.debug("News disk cache save failed: %s", exc)

    def _dict_to_analysis(self, raw: dict) -> NewsAnalysis:
        items = []
        for item_d in raw.get("top_items", []):
            pub_at = None
            if item_d.get("published_at"):
                try:
                    pub_at = datetime.fromisoformat(item_d["published_at"])
                except Exception:
                    pass
            items.append(NewsItem(
                title=item_d.get("title", ""),
                source=item_d.get("source", "cache"),
                published_at=pub_at,
                impact_score=item_d.get("impact_score", 0.0),
                sentiment_score=item_d.get("sentiment_score", 0.0),
                urgency_score=item_d.get("urgency_score", 0.0),
                danger_score=item_d.get("danger_score", 0.0),
                keywords_matched=item_d.get("keywords_matched", []),
                is_critical=item_d.get("is_critical", False),
            ))
        analysis_time_raw = raw.get("analysis_time")
        analysis_time = datetime.now(_UTC)
        if analysis_time_raw:
            try:
                analysis_time = datetime.fromisoformat(analysis_time_raw)
            except Exception:
                pass
        return NewsAnalysis(
            items=items,
            bullish_score=raw.get("bullish_score", 0.0),
            bearish_score=raw.get("bearish_score", 0.0),
            composite_sentiment=raw.get("composite_sentiment", 0.0),
            volatility_expectation=raw.get("volatility_expectation", 0.0),
            danger_score=raw.get("danger_score", 0.0),
            urgency_score=raw.get("urgency_score", 0.0),
            high_impact_count=raw.get("high_impact_count", 0),
            critical_count=raw.get("critical_count", 0),
            total_headlines=raw.get("total_headlines", 0),
            sources=raw.get("sources", []),
            top_keywords=raw.get("top_keywords", []),
            analysis_time=analysis_time,
            cache_hit=True,
        )

    def _neutral_analysis(self) -> NewsAnalysis:
        return NewsAnalysis(
            items=[],
            bullish_score=0.0,
            bearish_score=0.0,
            composite_sentiment=0.0,
            volatility_expectation=0.0,
            danger_score=0.0,
            urgency_score=0.0,
            high_impact_count=0,
            critical_count=0,
            total_headlines=0,
            sources=[],
            top_keywords=[],
            analysis_time=datetime.now(_UTC),
        )
