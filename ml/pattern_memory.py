"""
Pattern Memory — Persistente Setup Patroon Geheugen
===================================================
Slaat winning en losing setup patronen op en maakt
ze beschikbaar voor toekomstige signalevaluatie.

Functies:
  - Opslaan van setup patronen per signal type
  - Identificeren van vergelijkbare setups
  - Historische win/loss verdeling per patroon
  - Export voor dashboard visualisatie
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

MEMORY_DIR = Path("memory")
PATTERN_FILE = MEMORY_DIR / "setup_patterns.json"


@dataclass
class SetupPattern:
    """Een geïdentificeerd setup patroon met statistieken."""

    pattern_id: str
    signal_type: str
    direction: str
    h4_regime: str
    d1_trend: str
    rsi_range: tuple[float, float]  # (min, max)
    session: str  # "london" | "ny" | "overlap" | "any"

    # Statistieken
    total_trades: int = 0
    winning_trades: int = 0
    total_pnl: float = 0.0
    avg_rr: float = 0.0
    avg_holding_minutes: float = 0.0
    last_updated: datetime = field(default_factory=datetime.utcnow)

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades

    @property
    def expectancy(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.total_pnl / self.total_trades

    @property
    def quality_score(self) -> float:
        if self.total_trades < 3:
            return 0.0
        return round(
            self.win_rate * math.log1p(self.total_trades) * max(0.1, self.avg_rr),
            3,
        )

    @property
    def is_recommended(self) -> bool:
        return self.total_trades >= 5 and self.win_rate >= 0.55 and self.expectancy > 0

    @property
    def is_blocked(self) -> bool:
        return self.total_trades >= 5 and self.win_rate <= 0.30

    def to_dict(self) -> dict:
        return {
            "pattern_id": self.pattern_id,
            "signal_type": self.signal_type,
            "direction": self.direction,
            "h4_regime": self.h4_regime,
            "d1_trend": self.d1_trend,
            "rsi_range": list(self.rsi_range),
            "session": self.session,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "total_pnl": round(self.total_pnl, 2),
            "win_rate": round(self.win_rate, 4),
            "avg_rr": round(self.avg_rr, 3),
            "avg_holding_minutes": round(self.avg_holding_minutes, 1),
            "expectancy": round(self.expectancy, 2),
            "quality_score": self.quality_score,
            "is_recommended": self.is_recommended,
            "is_blocked": self.is_blocked,
            "last_updated": self.last_updated.isoformat(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> SetupPattern:
        return cls(
            pattern_id=d["pattern_id"],
            signal_type=d["signal_type"],
            direction=d["direction"],
            h4_regime=d["h4_regime"],
            d1_trend=d["d1_trend"],
            rsi_range=tuple(d["rsi_range"]),
            session=d.get("session", "any"),
            total_trades=d.get("total_trades", 0),
            winning_trades=d.get("winning_trades", 0),
            total_pnl=d.get("total_pnl", 0.0),
            avg_rr=d.get("avg_rr", 0.0),
            avg_holding_minutes=d.get("avg_holding_minutes", 0.0),
            last_updated=datetime.fromisoformat(d.get("last_updated", datetime.now(timezone.utc).isoformat())),
        )


@dataclass
class PatternMatch:
    """Resultaat van een patroonzoekopdracht."""

    pattern: SetupPattern
    similarity: float  # 0.0 - 1.0
    recommendation: str  # "strong_buy" | "buy" | "neutral" | "avoid" | "block"
    confidence_adjustment: float  # -0.3 tot +0.3 aanpassing op ML confidence


class PatternMemory:
    """
    Persistente setup patroon geheugen.

    Werkt onafhankelijk van het ML model — slaat patroonstatistieken
    op in een JSON bestand dat overleeft tussen sessies.

    Gebruik:
        memory = PatternMemory()
        memory.record(signal_type="A_EMACROSS", direction="long",
                      h4_regime="STERK_BULL", d1_trend="bull",
                      rsi14=55.0, session="london", pnl=320.0, rr=1.8)
        match = memory.find_best_match(signal_type="A_EMACROSS",
                                        direction="long", h4_regime="STERK_BULL",
                                        d1_trend="bull", rsi14=54.0, session="london")
    """

    def __init__(self, memory_dir: Path | None = None):
        self._patterns: dict[str, SetupPattern] = {}
        self._memory_dir = memory_dir or MEMORY_DIR
        self._memory_dir.mkdir(parents=True, exist_ok=True)
        self._pattern_file = self._memory_dir / "setup_patterns.json"
        self._load()

    # ─────────────────────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────────────────────

    def record(
        self,
        signal_type: str,
        direction: str,
        h4_regime: str,
        d1_trend: str,
        rsi14: float,
        session: str,
        pnl: float,
        rr: float = 1.0,
        holding_minutes: float = 60.0,
    ) -> SetupPattern:
        """Registreer het resultaat van een gesloten trade."""
        rsi_bucket = self._rsi_bucket(rsi14)
        pattern_id = self._make_pattern_id(signal_type, direction, h4_regime, d1_trend, rsi_bucket, session)

        if pattern_id not in self._patterns:
            self._patterns[pattern_id] = SetupPattern(
                pattern_id=pattern_id,
                signal_type=signal_type,
                direction=direction,
                h4_regime=h4_regime,
                d1_trend=d1_trend,
                rsi_range=self._rsi_range(rsi_bucket),
                session=session,
            )

        pattern = self._patterns[pattern_id]
        pattern.total_trades += 1
        if pnl > 0:
            pattern.winning_trades += 1
        pattern.total_pnl += pnl

        # Running average voor RR en holding time
        n = pattern.total_trades
        pattern.avg_rr = ((pattern.avg_rr * (n - 1)) + rr) / n
        pattern.avg_holding_minutes = ((pattern.avg_holding_minutes * (n - 1)) + holding_minutes) / n
        pattern.last_updated = datetime.now(timezone.utc)

        self._save()
        logger.debug(
            "Patroon geüpdated: %s win_rate=%.0f%% trades=%d",
            pattern_id,
            pattern.win_rate * 100,
            pattern.total_trades,
        )
        return pattern

    def find_best_match(
        self,
        signal_type: str,
        direction: str,
        h4_regime: str,
        d1_trend: str,
        rsi14: float,
        session: str = "any",
    ) -> PatternMatch | None:
        """
        Zoek het meest vergelijkbare patroon en geef een aanbeveling.
        Retourneert None als geen patroon gevonden.
        """
        rsi_bucket = self._rsi_bucket(rsi14)
        pattern_id = self._make_pattern_id(signal_type, direction, h4_regime, d1_trend, rsi_bucket, session)

        # Exact match
        if pattern_id in self._patterns:
            return self._make_match(self._patterns[pattern_id], similarity=1.0)

        # Fuzzy match: zelfde signal_type + direction, vergelijkbaar regime
        candidates = [p for p in self._patterns.values() if p.signal_type == signal_type and p.direction == direction]
        if not candidates:
            return None

        best = max(candidates, key=lambda p: self._similarity(p, h4_regime, d1_trend, rsi_bucket, session))
        sim = self._similarity(best, h4_regime, d1_trend, rsi_bucket, session)
        if sim < 0.3:
            return None

        return self._make_match(best, similarity=sim)

    def get_all_patterns(self, min_trades: int = 3) -> list[dict]:
        """Geeft alle patronen terug als dict lijst."""
        return [
            p.to_dict()
            for p in sorted(
                (p for p in self._patterns.values() if p.total_trades >= min_trades),
                key=lambda p: p.quality_score,
                reverse=True,
            )
        ]

    def get_recommended_setups(self) -> list[dict]:
        """Geeft aanbevolen setup types terug (win_rate > 55%, min 5 trades)."""
        return [p.to_dict() for p in self._patterns.values() if p.is_recommended]

    def get_blocked_setups(self) -> list[dict]:
        """Geeft geblokkeerde setup types terug (win_rate < 30%, min 5 trades)."""
        return [p.to_dict() for p in self._patterns.values() if p.is_blocked]

    def get_stats(self) -> dict:
        """Globale statistieken van het geheugen."""
        if not self._patterns:
            return {"total_patterns": 0, "total_trades": 0, "overall_win_rate": 0.0}

        total = sum(p.total_trades for p in self._patterns.values())
        wins = sum(p.winning_trades for p in self._patterns.values())
        total_pnl = sum(p.total_pnl for p in self._patterns.values())
        recommended = sum(1 for p in self._patterns.values() if p.is_recommended)
        blocked = sum(1 for p in self._patterns.values() if p.is_blocked)

        return {
            "total_patterns": len(self._patterns),
            "total_trades": total,
            "total_wins": wins,
            "overall_win_rate": round(wins / total, 4) if total > 0 else 0.0,
            "total_pnl": round(total_pnl, 2),
            "recommended_patterns": recommended,
            "blocked_patterns": blocked,
        }

    # ─────────────────────────────────────────────────────────────
    # PRIVÉ
    # ─────────────────────────────────────────────────────────────

    @staticmethod
    def _make_pattern_id(
        signal_type: str,
        direction: str,
        h4_regime: str,
        d1_trend: str,
        rsi_bucket: str,
        session: str,
    ) -> str:
        return f"{signal_type}_{direction}_{h4_regime}_{d1_trend}_{rsi_bucket}_{session}"

    @staticmethod
    def _rsi_bucket(rsi: float) -> str:
        if rsi < 35:
            return "OS"  # oversold
        if rsi < 45:
            return "LOW"
        if rsi < 55:
            return "MID"
        if rsi < 65:
            return "HIGH"
        return "OB"  # overbought

    @staticmethod
    def _rsi_range(bucket: str) -> tuple[float, float]:
        ranges = {"OS": (0, 35), "LOW": (35, 45), "MID": (45, 55), "HIGH": (55, 65), "OB": (65, 100)}
        return ranges.get(bucket, (0, 100))

    def _similarity(
        self,
        pattern: SetupPattern,
        h4_regime: str,
        d1_trend: str,
        rsi_bucket: str,
        session: str,
    ) -> float:
        score = 0.0
        if pattern.h4_regime == h4_regime:
            score += 0.35
        elif self._regime_compatible(pattern.h4_regime, h4_regime):
            score += 0.15
        if pattern.d1_trend == d1_trend:
            score += 0.25
        if pattern.rsi_range == self._rsi_range(rsi_bucket):
            score += 0.25
        if pattern.session == session or pattern.session == "any":
            score += 0.15
        return round(min(1.0, score), 3)

    @staticmethod
    def _regime_compatible(a: str, b: str) -> bool:
        bull = {"STERK_BULL", "BULL", "ZWAK_BULL"}
        bear = {"STERK_BEAR", "BEAR", "ZWAK_BEAR"}
        return (a in bull and b in bull) or (a in bear and b in bear)

    @staticmethod
    def _make_match(pattern: SetupPattern, similarity: float) -> PatternMatch:
        if pattern.is_blocked:
            rec = "block"
            adj = -0.3
        elif pattern.is_recommended and similarity >= 0.7:
            rec = "strong_buy" if pattern.win_rate >= 0.65 else "buy"
            adj = min(0.3, (pattern.win_rate - 0.5) * 0.6)
        elif pattern.win_rate >= 0.55:
            rec = "buy"
            adj = min(0.15, (pattern.win_rate - 0.5) * 0.3)
        elif pattern.win_rate <= 0.40:
            rec = "avoid"
            adj = max(-0.15, (pattern.win_rate - 0.5) * 0.3)
        else:
            rec = "neutral"
            adj = 0.0

        return PatternMatch(
            pattern=pattern,
            similarity=similarity,
            recommendation=rec,
            confidence_adjustment=round(adj * similarity, 4),
        )

    def _load(self) -> None:
        if not self._pattern_file.exists():
            return
        try:
            data = json.loads(self._pattern_file.read_text(encoding="utf-8"))
            self._patterns = {pid: SetupPattern.from_dict(p) for pid, p in data.get("patterns", {}).items()}
            logger.debug("PatternMemory: %d patronen geladen", len(self._patterns))
        except Exception as exc:
            logger.warning("PatternMemory: laden mislukt: %s", exc)

    def _save(self) -> None:
        try:
            data = {"patterns": {pid: p.to_dict() for pid, p in self._patterns.items()}}
            self._pattern_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("PatternMemory: opslaan mislukt: %s", exc)
