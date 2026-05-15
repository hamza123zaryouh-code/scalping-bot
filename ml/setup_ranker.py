"""
Setup Ranker — Gecombineerde AI Confidence & Pattern Score
==========================================================
Combineert feedback_engine (ML) met pattern_memory (historisch)
tot één gecombineerde score per setup.

Score componenten:
  1. ML model confidence (GradientBoosting ensemble)   — 40%
  2. Pattern memory win rate                           — 30%
  3. Signal priority (A > B > E > C > F > D)           — 20%
  4. Regime strength (STERK > gewoon > ZWAK)           — 10%

Output:
  - combined_score: 0.0 - 1.0
  - recommendation: "execute" | "execute_reduced" | "skip" | "block"
  - risk_multiplier: 0.0 - 1.2 (aanpassing op base risk%)
  - explanation: menselijk leesbare uitleg
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

SIGNAL_PRIORITY_NORM = {
    "A_EMACROSS": 1.0,
    "B_MACDCROSS": 0.83,
    "E_BOS": 0.67,
    "C_MOMENTUM": 0.50,
    "F_MSS": 0.33,
    "D_PULLBACK": 0.17,
}

REGIME_STRENGTH = {
    "STERK_BULL": 1.0, "STERK_BEAR": 1.0,
    "BULL": 0.75, "BEAR": 0.75,
    "ZWAK_BULL": 0.50, "ZWAK_BEAR": 0.50,
    "CHOPPY": 0.0,
}


@dataclass
class RankingResult:
    """Volledig rankingsresultaat voor een setup."""
    combined_score: float           # 0.0 - 1.0
    ml_confidence: float            # 0.0 - 1.0
    pattern_score: float            # 0.0 - 1.0
    priority_score: float           # 0.0 - 1.0
    regime_score: float             # 0.0 - 1.0
    pattern_recommendation: str     # block | avoid | neutral | buy | strong_buy | unknown
    recommendation: str             # execute | execute_reduced | skip | block
    risk_multiplier: float          # aanpassing op basis risk%
    explanation: str
    pattern_trades: int             # hoeveel trades in het patroon
    pattern_win_rate: float         # win rate van het patroon

    def to_dict(self) -> dict:
        return {
            "combined_score": round(self.combined_score, 4),
            "ml_confidence": round(self.ml_confidence, 4),
            "pattern_score": round(self.pattern_score, 4),
            "priority_score": round(self.priority_score, 4),
            "regime_score": round(self.regime_score, 4),
            "pattern_recommendation": self.pattern_recommendation,
            "recommendation": self.recommendation,
            "risk_multiplier": round(self.risk_multiplier, 3),
            "explanation": self.explanation,
            "pattern_trades": self.pattern_trades,
            "pattern_win_rate": round(self.pattern_win_rate, 4),
        }


class SetupRanker:
    """
    Gecombineerde AI + patroon score voor setup evaluatie.

    Gebruik:
        ranker = SetupRanker(feedback_engine, pattern_memory)
        result = ranker.rank(
            signal_type="A_EMACROSS",
            direction="long",
            h4_regime="STERK_BULL",
            d1_trend="bull",
            rsi14=55.0,
            session="london",
            features={"rsi14": 55.0, "adx14": 22.0, ...}
        )
        if result.recommendation in ("execute", "execute_reduced"):
            adjusted_risk = base_risk * result.risk_multiplier
    """

    def __init__(self, feedback_engine=None, pattern_memory=None):
        self._feedback = feedback_engine
        self._patterns = pattern_memory

    def rank(
        self,
        signal_type: str,
        direction: str,
        h4_regime: str,
        d1_trend: str,
        rsi14: float,
        session: str,
        features: Optional[dict] = None,
    ) -> RankingResult:
        """
        Genereer een volledig rankingsresultaat voor een setup.
        """
        # 1. ML confidence (40% gewicht)
        ml_conf = 0.5
        if self._feedback is not None and features:
            from ml.feedback_engine import MODEL_FEATURES, H4_REGIME_SCORE, SIGNAL_PRIORITY_MAP
            feat = dict(features)
            feat["h4_regime_score"] = float(H4_REGIME_SCORE.get(h4_regime, 0))
            feat["d1_bull"] = 1.0 if d1_trend == "bull" else (0.0 if d1_trend == "neutral" else -1.0)
            feat["signal_priority"] = float(SIGNAL_PRIORITY_MAP.get(signal_type, 0))
            hour = features.get("hour_of_day", 10)
            feat["session_score"] = 1.0 if (7 <= hour < 12 or 13 <= hour <= 17) else (0.5 if hour == 12 else 0.0)
            ml_conf = self._feedback.predict_confidence(feat)

        # 2. Pattern score (30% gewicht)
        pattern_score = 0.5
        pattern_recommendation = "unknown"
        pattern_trades = 0
        pattern_win_rate = 0.0
        confidence_adjustment = 0.0

        if self._patterns is not None:
            match = self._patterns.find_best_match(
                signal_type=signal_type, direction=direction,
                h4_regime=h4_regime, d1_trend=d1_trend,
                rsi14=rsi14, session=session,
            )
            if match:
                pattern_score = match.pattern.win_rate
                pattern_recommendation = match.recommendation
                confidence_adjustment = match.confidence_adjustment
                pattern_trades = match.pattern.total_trades
                pattern_win_rate = match.pattern.win_rate

        # 3. Signal priority (20% gewicht)
        priority_score = SIGNAL_PRIORITY_NORM.get(signal_type, 0.17)

        # 4. Regime strength (10% gewicht)
        regime_score = REGIME_STRENGTH.get(h4_regime, 0.0)

        # Gecombineerde score
        combined = (
            ml_conf * 0.40 +
            pattern_score * 0.30 +
            priority_score * 0.20 +
            regime_score * 0.10
        ) + confidence_adjustment

        combined = round(max(0.0, min(1.0, combined)), 4)

        # Aanbeveling
        if pattern_recommendation == "block":
            recommendation = "block"
            risk_mult = 0.0
            explanation = f"GEBLOKKEERD: patroon {signal_type}_{direction} heeft <30% win rate"
        elif combined >= 0.70:
            recommendation = "execute"
            risk_mult = min(1.2, 1.0 + (combined - 0.70) * 0.67)
            explanation = f"UITVOEREN: score {combined:.0%} — hoog vertrouwen"
        elif combined >= 0.55:
            recommendation = "execute_reduced"
            risk_mult = 0.75
            explanation = f"UITVOEREN (verlaagd risico): score {combined:.0%}"
        elif combined >= 0.40:
            recommendation = "skip"
            risk_mult = 0.0
            explanation = f"OVERSLAAN: score {combined:.0%} — onvoldoende vertrouwen"
        else:
            recommendation = "skip"
            risk_mult = 0.0
            explanation = f"OVERSLAAN: score {combined:.0%} — laag vertrouwen"

        if pattern_trades >= 5:
            explanation += f" | Patroon: {pattern_win_rate:.0%} WR op {pattern_trades} trades"

        return RankingResult(
            combined_score=combined,
            ml_confidence=round(ml_conf, 4),
            pattern_score=round(pattern_score, 4),
            priority_score=round(priority_score, 4),
            regime_score=round(regime_score, 4),
            pattern_recommendation=pattern_recommendation,
            recommendation=recommendation,
            risk_multiplier=round(risk_mult, 3),
            explanation=explanation,
            pattern_trades=pattern_trades,
            pattern_win_rate=round(pattern_win_rate, 4),
        )

    def batch_rank(self, setups: list[dict]) -> list[dict]:
        """Rank meerdere setups tegelijk — voor optimizer dashboard."""
        results = []
        for setup in setups:
            result = self.rank(
                signal_type=setup.get("signal_type", "D_PULLBACK"),
                direction=setup.get("direction", "long"),
                h4_regime=setup.get("h4_regime", "CHOPPY"),
                d1_trend=setup.get("d1_trend", "neutral"),
                rsi14=float(setup.get("rsi14", 50.0)),
                session=setup.get("session", "any"),
                features=setup.get("features"),
            )
            results.append({**setup, "ranking": result.to_dict()})
        return sorted(results, key=lambda x: x["ranking"]["combined_score"], reverse=True)


# ─────────────────────────────────────────────────────────────────
# SINGLETON
# ─────────────────────────────────────────────────────────────────

_ranker_instance: Optional[SetupRanker] = None


def get_ranker(feedback_engine=None, pattern_memory=None) -> SetupRanker:
    global _ranker_instance
    if _ranker_instance is None:
        _ranker_instance = SetupRanker(feedback_engine, pattern_memory)
    return _ranker_instance
