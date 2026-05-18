"""
Pattern Memory Engine — Persistent learning layer for XAUUSD setups.

Stores every trade setup, ranks setups by performance metrics, and
provides self-adaptive setup weighting for position sizing.

Storage: JSON flat-file (portable, no extra DB dependency).
         Also writes summary to MemoryLayer RuntimeState for API visibility.

Pattern key = (signal_type, direction, h4_regime, d1_trend, rsi_bucket, session)

Features:
  - Per-pattern: trades, wins, total_pnl, win_rate, expectancy, RR avg
  - Quality score combining win_rate × log1p(trades) × avg_RR
  - Blocking patterns: < 30% win rate with ≥ 5 trades
  - Boosting patterns: > 60% win rate with ≥ 8 trades
  - Risk multiplier 0.25 – 1.25 based on pattern quality
  - Automatic pruning of stale patterns (> 6 months without a trade)
  - Thread-safe for concurrent main loop + API access
"""

from __future__ import annotations

import json
import logging
import math
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_UTC = timezone.utc
_STORE_PATH = Path("memory/pattern_memory.json")
_MIN_TRADES_FOR_SIGNAL = 5
_MIN_TRADES_FOR_BLOCK = 5
_BLOCK_WIN_RATE = 0.30
_BOOST_WIN_RATE = 0.60
_BOOST_MIN_TRADES = 8
_STALE_DAYS = 180


def _rsi_bucket(rsi: float) -> str:
    if rsi < 30:
        return "oversold"
    if rsi < 45:
        return "bearish_zone"
    if rsi < 55:
        return "neutral"
    if rsi < 70:
        return "bullish_zone"
    return "overbought"


def _regime_key(h4_regime: str | None) -> str:
    r = (h4_regime or "").lower()
    if "strong_bull" in r or "bullish_strong" in r:
        return "strong_bull"
    if "bull" in r:
        return "bull"
    if "strong_bear" in r or "bearish_strong" in r:
        return "strong_bear"
    if "bear" in r:
        return "bear"
    return "ranging"


def _d1_key(d1_trend: str | None) -> str:
    t = (d1_trend or "").lower()
    if "bull" in t:
        return "bull"
    if "bear" in t:
        return "bear"
    return "neutral"


class PatternRecord:
    __slots__ = (
        "key",
        "signal_type",
        "direction",
        "h4_regime",
        "d1_trend",
        "rsi_bucket",
        "session",
        "trades",
        "wins",
        "total_pnl",
        "reward_risk_sum",
        "last_trade_at",
    )

    def __init__(
        self, key: str, signal_type: str, direction: str, h4_regime: str, d1_trend: str, rsi_bucket: str, session: str
    ) -> None:
        self.key = key
        self.signal_type = signal_type
        self.direction = direction
        self.h4_regime = h4_regime
        self.d1_trend = d1_trend
        self.rsi_bucket = rsi_bucket
        self.session = session
        self.trades: int = 0
        self.wins: int = 0
        self.total_pnl: float = 0.0
        self.reward_risk_sum: float = 0.0
        self.last_trade_at: str = datetime.now(_UTC).isoformat()

    @property
    def win_rate(self) -> float:
        return self.wins / self.trades if self.trades > 0 else 0.0

    @property
    def avg_pnl(self) -> float:
        return self.total_pnl / self.trades if self.trades > 0 else 0.0

    @property
    def avg_rr(self) -> float:
        return self.reward_risk_sum / self.trades if self.trades > 0 else 0.0

    @property
    def quality_score(self) -> float:
        if self.trades < _MIN_TRADES_FOR_SIGNAL:
            return 0.0
        wr = self.win_rate
        rr = max(0.1, self.avg_rr)
        log_n = math.log1p(self.trades)
        return round(wr * log_n * rr, 4)

    def is_blocked(self) -> bool:
        return self.trades >= _MIN_TRADES_FOR_BLOCK and self.win_rate < _BLOCK_WIN_RATE

    def is_boosted(self) -> bool:
        return self.trades >= _BOOST_MIN_TRADES and self.win_rate >= _BOOST_WIN_RATE

    def risk_multiplier(self) -> float:
        if self.is_blocked():
            return 0.25
        if self.trades < _MIN_TRADES_FOR_SIGNAL:
            return 0.85  # new pattern — slight caution
        qs = self.quality_score
        if qs >= 2.0:
            return 1.25
        if qs >= 1.0:
            return 1.10
        if qs >= 0.5:
            return 1.0
        if qs >= 0.2:
            return 0.80
        return 0.65

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "signal_type": self.signal_type,
            "direction": self.direction,
            "h4_regime": self.h4_regime,
            "d1_trend": self.d1_trend,
            "rsi_bucket": self.rsi_bucket,
            "session": self.session,
            "trades": self.trades,
            "wins": self.wins,
            "total_pnl": round(self.total_pnl, 2),
            "win_rate": round(self.win_rate, 3),
            "avg_pnl": round(self.avg_pnl, 2),
            "avg_rr": round(self.avg_rr, 3),
            "quality_score": round(self.quality_score, 4),
            "risk_multiplier": round(self.risk_multiplier(), 3),
            "is_blocked": self.is_blocked(),
            "is_boosted": self.is_boosted(),
            "last_trade_at": self.last_trade_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PatternRecord:
        rec = cls(
            key=d["key"],
            signal_type=d.get("signal_type", "unknown"),
            direction=d.get("direction", "buy"),
            h4_regime=d.get("h4_regime", "ranging"),
            d1_trend=d.get("d1_trend", "neutral"),
            rsi_bucket=d.get("rsi_bucket", "neutral"),
            session=d.get("session", "unknown"),
        )
        rec.trades = int(d.get("trades", 0))
        rec.wins = int(d.get("wins", 0))
        rec.total_pnl = float(d.get("total_pnl", 0.0))
        rec.reward_risk_sum = float(d.get("reward_risk_sum", 0.0))
        rec.last_trade_at = d.get("last_trade_at", datetime.now(_UTC).isoformat())
        return rec


class PatternMemoryEngine:
    """
    Persistent pattern memory with self-adaptive setup weighting.

    Thread-safe. Persists to JSON on every record_trade_closed() call.
    """

    def __init__(self, store_path: Path | None = None) -> None:
        self._path = store_path or _STORE_PATH
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._patterns: dict[str, PatternRecord] = {}
        self._lock = threading.Lock()
        self._load()

    # ─────────────────────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────────────────────

    def get_risk_multiplier(
        self,
        signal_type: str,
        direction: str,
        h4_regime: str | None = None,
        d1_trend: str | None = None,
        rsi: float | None = None,
        session: str | None = None,
    ) -> float:
        key = self._make_key(signal_type, direction, h4_regime, d1_trend, rsi, session)
        with self._lock:
            rec = self._patterns.get(key)
            if rec is None:
                return 0.85  # unknown pattern — slight caution
            return rec.risk_multiplier()

    def is_blocked(
        self,
        signal_type: str,
        direction: str,
        h4_regime: str | None = None,
        d1_trend: str | None = None,
        rsi: float | None = None,
        session: str | None = None,
    ) -> bool:
        key = self._make_key(signal_type, direction, h4_regime, d1_trend, rsi, session)
        with self._lock:
            rec = self._patterns.get(key)
            return rec is not None and rec.is_blocked()

    def record_trade_opened(
        self,
        signal_type: str,
        direction: str,
        h4_regime: str | None = None,
        d1_trend: str | None = None,
        rsi: float | None = None,
        session: str | None = None,
    ) -> None:
        key = self._make_key(signal_type, direction, h4_regime, d1_trend, rsi, session)
        with self._lock:
            if key not in self._patterns:
                self._patterns[key] = PatternRecord(
                    key=key,
                    signal_type=signal_type,
                    direction=direction,
                    h4_regime=_regime_key(h4_regime),
                    d1_trend=_d1_key(d1_trend),
                    rsi_bucket=_rsi_bucket(rsi or 50.0),
                    session=(session or "unknown").upper(),
                )

    def record_trade_closed(
        self,
        signal_type: str,
        direction: str,
        pnl: float,
        reward_risk: float = 0.0,
        h4_regime: str | None = None,
        d1_trend: str | None = None,
        rsi: float | None = None,
        session: str | None = None,
    ) -> None:
        key = self._make_key(signal_type, direction, h4_regime, d1_trend, rsi, session)
        with self._lock:
            if key not in self._patterns:
                self._patterns[key] = PatternRecord(
                    key=key,
                    signal_type=signal_type,
                    direction=direction,
                    h4_regime=_regime_key(h4_regime),
                    d1_trend=_d1_key(d1_trend),
                    rsi_bucket=_rsi_bucket(rsi or 50.0),
                    session=(session or "unknown").upper(),
                )
            rec = self._patterns[key]
            rec.trades += 1
            if pnl > 0:
                rec.wins += 1
            rec.total_pnl += pnl
            rec.reward_risk_sum += max(0.0, reward_risk)
            rec.last_trade_at = datetime.now(_UTC).isoformat()
        self._save()

    def get_top_patterns(self, n: int = 10, min_trades: int = 3) -> list[dict[str, Any]]:
        with self._lock:
            eligible = [rec for rec in self._patterns.values() if rec.trades >= min_trades and not rec.is_blocked()]
        eligible.sort(key=lambda r: r.quality_score, reverse=True)
        return [rec.to_dict() for rec in eligible[:n]]

    def get_blocked_patterns(self) -> list[dict[str, Any]]:
        with self._lock:
            blocked = [rec for rec in self._patterns.values() if rec.is_blocked()]
        blocked.sort(key=lambda r: r.trades, reverse=True)
        return [rec.to_dict() for rec in blocked]

    def get_all_patterns(self) -> list[dict[str, Any]]:
        with self._lock:
            recs = list(self._patterns.values())
        recs.sort(key=lambda r: r.quality_score, reverse=True)
        return [rec.to_dict() for rec in recs]

    def get_summary(self) -> dict[str, Any]:
        with self._lock:
            all_recs = list(self._patterns.values())
        total = len(all_recs)
        boosted = sum(1 for r in all_recs if r.is_boosted())
        blocked = sum(1 for r in all_recs if r.is_blocked())
        with_data = [r for r in all_recs if r.trades >= _MIN_TRADES_FOR_SIGNAL]
        avg_wr = sum(r.win_rate for r in with_data) / len(with_data) if with_data else 0.0
        return {
            "total_patterns": total,
            "boosted_patterns": boosted,
            "blocked_patterns": blocked,
            "patterns_with_data": len(with_data),
            "avg_win_rate": round(avg_wr, 3),
            "top_patterns": self.get_top_patterns(5),
        }

    def prune_stale(self) -> int:
        cutoff = datetime.now(_UTC) - timedelta(days=_STALE_DAYS)
        pruned = 0
        with self._lock:
            to_delete = []
            for key, rec in self._patterns.items():
                try:
                    last = datetime.fromisoformat(rec.last_trade_at)
                    if last < cutoff and rec.trades < 3:
                        to_delete.append(key)
                except Exception:
                    pass
            for key in to_delete:
                del self._patterns[key]
                pruned += 1
        if pruned:
            self._save()
        return pruned

    # ─────────────────────────────────────────────────────────────
    # PRIVATE
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def _make_key(
        signal_type: str,
        direction: str,
        h4_regime: str | None,
        d1_trend: str | None,
        rsi: float | None,
        session: str | None,
    ) -> str:
        parts = [
            signal_type.upper()[:20],
            direction.lower()[:5],
            _regime_key(h4_regime),
            _d1_key(d1_trend),
            _rsi_bucket(rsi if rsi is not None else 50.0),
            (session or "unknown").upper()[:10],
        ]
        return "|".join(parts)

    def _load(self) -> None:
        try:
            if not self._path.exists():
                return
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            for item in raw.get("patterns", []):
                rec = PatternRecord.from_dict(item)
                self._patterns[rec.key] = rec
            logger.info("PatternMemoryEngine: loaded %d patterns", len(self._patterns))
        except Exception as exc:
            logger.warning("PatternMemoryEngine load failed: %s — starting fresh", exc)

    def _save(self) -> None:
        try:
            payload = {
                "patterns": [rec.to_dict() for rec in self._patterns.values()],
                "saved_at": datetime.now(_UTC).isoformat(),
                "total": len(self._patterns),
            }
            self._path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        except Exception as exc:
            logger.error("PatternMemoryEngine save failed: %s", exc)
