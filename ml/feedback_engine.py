"""
ML Feedback Engine — Echte Learning Pipeline voor XAUUSD
=========================================================
Verzamelt setup-features van elke gesloten trade en leert
welke condities leiden tot winnende of verliezende setups.

Pipeline:
  1. TradeRecord binnenkomt na sluiting
  2. Features worden genormaliseerd en opgeslagen
  3. Model traint op de volledige history (minimaal 20 trades)
  4. Model geeft confidence scores op nieuwe setups
  5. Parametersuggesties worden afgeleid uit winning patterns

Compatibel met:
  - autonomous_xauusd/memory_layer.py (data source)
  - autonomous_xauusd/brain_layer.py (model training)
  - core/strategy_engine.py (feature names)
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

MIN_TRAINING_SAMPLES = 20
MIN_CONFIDENCE_THRESHOLD = 0.45
MODEL_FEATURES = [
    "rsi14", "adx14", "macd_hist", "h4_adx", "h4_regime_score",
    "d1_bull", "dist21", "atr14", "volatility_ratio",
    "hour_of_day", "day_of_week", "session_score",
    "signal_priority", "sentiment_score",
]

SIGNAL_PRIORITY_MAP = {
    "A_EMACROSS": 6, "B_MACDCROSS": 5, "E_BOS": 4,
    "C_MOMENTUM": 3, "F_MSS": 2, "D_PULLBACK": 1,
}

H4_REGIME_SCORE = {
    "STERK_BULL": 3, "BULL": 2, "ZWAK_BULL": 1,
    "CHOPPY": 0,
    "ZWAK_BEAR": -1, "BEAR": -2, "STERK_BEAR": -3,
}


@dataclass
class TradeFeatureRecord:
    """Feature vector van één gesloten trade — input voor het ML model."""
    broker_ticket: str
    signal_type: str
    direction: str
    rsi14: float
    adx14: float
    macd_hist: float
    h4_adx: float
    h4_regime: str
    d1_trend: str
    dist21: float
    atr14: float
    volatility_ratio: float
    hour_of_day: int
    day_of_week: int
    sentiment_score: float
    pnl: float
    rr_ratio: float
    market_regime: str
    holding_minutes: float
    source: str = "live"        # "live" | "backtest" | "paper"
    recorded_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def is_winner(self) -> bool:
        return self.pnl > 0

    @property
    def h4_regime_score(self) -> float:
        return float(H4_REGIME_SCORE.get(self.h4_regime, 0))

    @property
    def d1_bull(self) -> float:
        return 1.0 if self.d1_trend == "bull" else (0.0 if self.d1_trend == "neutral" else -1.0)

    @property
    def session_score(self) -> float:
        h = self.hour_of_day
        if 7 <= h < 12:  return 1.0   # London open — premium
        if 13 <= h <= 17: return 1.0  # NY open — premium
        if h == 12:       return 0.5  # Overlap — standard
        return 0.0                    # buiten sessie

    @property
    def signal_priority(self) -> float:
        return float(SIGNAL_PRIORITY_MAP.get(self.signal_type, 0))

    def to_feature_vector(self) -> dict:
        return {
            "rsi14": self.rsi14,
            "adx14": self.adx14,
            "macd_hist": self.macd_hist,
            "h4_adx": self.h4_adx,
            "h4_regime_score": self.h4_regime_score,
            "d1_bull": self.d1_bull,
            "dist21": self.dist21,
            "atr14": self.atr14,
            "volatility_ratio": self.volatility_ratio,
            "hour_of_day": self.hour_of_day,
            "day_of_week": self.day_of_week,
            "session_score": self.session_score,
            "signal_priority": self.signal_priority,
            "sentiment_score": self.sentiment_score,
        }

    def to_dict(self) -> dict:
        return {
            **self.to_feature_vector(),
            "broker_ticket": self.broker_ticket,
            "signal_type": self.signal_type,
            "direction": self.direction,
            "pnl": self.pnl,
            "rr_ratio": self.rr_ratio,
            "market_regime": self.market_regime,
            "holding_minutes": self.holding_minutes,
            "source": self.source,
            "is_winner": self.is_winner,
        }


@dataclass
class ModelMetrics:
    """Performance metrics van het feedback model."""
    accuracy: float
    precision: float
    recall: float
    f1: float
    sample_count: int
    win_rate: float
    trained_at: datetime = field(default_factory=datetime.utcnow)
    feature_importances: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "accuracy": round(self.accuracy, 4),
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "sample_count": self.sample_count,
            "win_rate": round(self.win_rate, 4),
            "trained_at": self.trained_at.isoformat(),
            "feature_importances": {k: round(v, 4) for k, v in self.feature_importances.items()},
        }


class FeedbackEngine:
    """
    Core ML feedback engine voor setup quality prediction.

    Gebruikt sklearn GradientBoosting als primair model
    met RandomForest als ensemble vote.

    Gebruik:
        engine = FeedbackEngine()
        engine.record_trade(trade_record)
        engine.train()
        confidence = engine.predict_confidence(features)
    """

    def __init__(self, artifact_path: Optional[Path] = None):
        self._records: list[TradeFeatureRecord] = []
        self._model_gb = None
        self._model_rf = None
        self._metrics: Optional[ModelMetrics] = None
        self._artifact_path = artifact_path or Path("artifacts/feedback_model.joblib")
        self._artifact_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_model()

    # ─────────────────────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────────────────────

    def record_trade(self, record: TradeFeatureRecord) -> None:
        """Voeg een gesloten trade toe aan de trainingsset."""
        self._records.append(record)
        logger.debug(
            "Trade geregistreerd: %s %s PnL=%.2f Winner=%s",
            record.signal_type, record.direction, record.pnl, record.is_winner,
        )

    def load_from_memory_layer(self, memory_layer) -> int:
        """Laad trades van de database (memory_layer) in de trainingsset."""
        try:
            df = memory_layer.fetch_training_frame()
            if df.empty:
                return 0

            loaded = 0
            existing_tickets = {r.broker_ticket for r in self._records}

            for _, row in df.iterrows():
                ticket = str(row.get("broker_ticket", ""))
                if ticket in existing_tickets:
                    continue

                try:
                    rec = self._row_to_record(row)
                    self._records.append(rec)
                    loaded += 1
                except Exception as exc:
                    logger.debug("Trade overgeslagen bij laden: %s", exc)

            logger.info("FeedbackEngine: %d trades geladen van memory_layer", loaded)
            return loaded

        except Exception as exc:
            logger.warning("FeedbackEngine: memory_layer laden mislukt: %s", exc)
            return 0

    def train(self) -> Optional[ModelMetrics]:
        """Train het model op de huidige recordset. Retourneert None als onvoldoende data."""
        if len(self._records) < MIN_TRAINING_SAMPLES:
            logger.info(
                "FeedbackEngine: onvoldoende data voor training (%d < %d)",
                len(self._records), MIN_TRAINING_SAMPLES,
            )
            return None

        try:
            from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
            from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score
            from sklearn.model_selection import train_test_split
            import joblib

            df = self._to_dataframe()
            X = df[MODEL_FEATURES].fillna(0.0)
            y = df["is_winner"].astype(int)

            if y.nunique() < 2:
                logger.warning("FeedbackEngine: alle trades zijn %s — niet nuttig om te trainen", "winst" if y.iloc[0] == 1 else "verlies")
                return None

            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=0.2, random_state=42, stratify=y
            )

            gb = GradientBoostingClassifier(
                n_estimators=100, max_depth=3, learning_rate=0.1,
                subsample=0.8, random_state=42,
            )
            gb.fit(X_train, y_train)

            rf = RandomForestClassifier(
                n_estimators=100, max_depth=4,
                min_samples_leaf=3, random_state=42,
            )
            rf.fit(X_train, y_train)

            # Ensemble vote
            gb_proba = gb.predict_proba(X_test)[:, 1]
            rf_proba = rf.predict_proba(X_test)[:, 1]
            ensemble_proba = (gb_proba * 0.6 + rf_proba * 0.4)
            y_pred = (ensemble_proba >= 0.5).astype(int)

            # Feature importance van GB
            fi = dict(zip(MODEL_FEATURES, gb.feature_importances_))

            metrics = ModelMetrics(
                accuracy=float(accuracy_score(y_test, y_pred)),
                precision=float(precision_score(y_test, y_pred, zero_division=0)),
                recall=float(recall_score(y_test, y_pred, zero_division=0)),
                f1=float(f1_score(y_test, y_pred, zero_division=0)),
                sample_count=len(df),
                win_rate=float(y.mean()),
                feature_importances=fi,
            )

            self._model_gb = gb
            self._model_rf = rf
            self._metrics = metrics

            joblib.dump({"gb": gb, "rf": rf, "features": MODEL_FEATURES}, self._artifact_path)
            logger.info(
                "FeedbackEngine: model getraind — accuracy=%.1f%% f1=%.1f%% samples=%d",
                metrics.accuracy * 100, metrics.f1 * 100, metrics.sample_count,
            )
            return metrics

        except ImportError:
            logger.warning("FeedbackEngine: scikit-learn niet beschikbaar — model training overgeslagen")
            return None
        except Exception as exc:
            logger.exception("FeedbackEngine: training mislukt: %s", exc)
            return None

    def predict_confidence(self, features: dict) -> float:
        """
        Geeft een confidence score voor een setup (0.0 - 1.0).
        Retourneert 0.5 (neutraal) als het model niet beschikbaar is.
        """
        if self._model_gb is None or self._model_rf is None:
            return 0.5

        try:
            import pandas as pd
            row = {k: features.get(k, 0.0) for k in MODEL_FEATURES}
            X = pd.DataFrame([row])

            gb_proba = self._model_gb.predict_proba(X)[0][1]
            rf_proba = self._model_rf.predict_proba(X)[0][1]
            ensemble = gb_proba * 0.6 + rf_proba * 0.4
            return float(round(max(0.0, min(1.0, ensemble)), 4))

        except Exception as exc:
            logger.debug("FeedbackEngine: confidence prediction mislukt: %s", exc)
            return 0.5

    def get_metrics(self) -> Optional[dict]:
        if self._metrics is None:
            return None
        return self._metrics.to_dict()

    def get_record_count(self) -> int:
        return len(self._records)

    def get_win_rate(self) -> float:
        if not self._records:
            return 0.0
        return sum(1 for r in self._records if r.is_winner) / len(self._records)

    def get_top_setups(self, n: int = 5) -> list[dict]:
        """Geeft de top-N winnende setup types terug."""
        from collections import defaultdict
        stats: dict[str, dict] = defaultdict(lambda: {"wins": 0, "total": 0, "total_pnl": 0.0})

        for rec in self._records:
            key = f"{rec.signal_type}_{rec.direction}"
            stats[key]["total"] += 1
            stats[key]["total_pnl"] += rec.pnl
            if rec.is_winner:
                stats[key]["wins"] += 1

        ranked = []
        for key, s in stats.items():
            win_rate = s["wins"] / s["total"] if s["total"] > 0 else 0.0
            ranked.append({
                "setup": key,
                "win_rate": round(win_rate, 3),
                "total_pnl": round(s["total_pnl"], 2),
                "count": s["total"],
                "score": round(win_rate * math.log1p(s["total"]) * (1 + s["total_pnl"] / 1000), 3),
            })

        return sorted(ranked, key=lambda x: x["score"], reverse=True)[:n]

    # ─────────────────────────────────────────────────────────────
    # PRIVÉ
    # ─────────────────────────────────────────────────────────────

    def _to_dataframe(self) -> pd.DataFrame:
        rows = []
        for rec in self._records:
            d = rec.to_feature_vector()
            d["is_winner"] = rec.is_winner
            d["pnl"] = rec.pnl
            d["rr_ratio"] = rec.rr_ratio
            d["signal_type"] = rec.signal_type
            rows.append(d)
        return pd.DataFrame(rows)

    def _load_model(self) -> None:
        if not self._artifact_path.exists():
            return
        try:
            import joblib
            data = joblib.load(self._artifact_path)
            self._model_gb = data.get("gb")
            self._model_rf = data.get("rf")
            logger.info("FeedbackEngine: model geladen van %s", self._artifact_path)
        except Exception as exc:
            logger.warning("FeedbackEngine: model laden mislukt: %s", exc)

    def _row_to_record(self, row) -> TradeFeatureRecord:
        opened_at = pd.to_datetime(row.get("opened_at", datetime.now(timezone.utc)))
        closed_at = pd.to_datetime(row.get("closed_at", opened_at))
        holding_minutes = max(0.0, (closed_at - opened_at).total_seconds() / 60.0) if pd.notna(closed_at) else 0.0
        atr = float(row.get("atr", 0.0) or 0.0)
        h4_atr = float(row.get("h4_atr", atr * 4) or (atr * 4))
        vol_ratio = (h4_atr / (atr * 4)) if atr > 0 else 1.0

        return TradeFeatureRecord(
            broker_ticket=str(row.get("broker_ticket", "")),
            signal_type=str(row.get("signal_type", "UNKNOWN")),
            direction=str(row.get("side", "unknown")),
            rsi14=float(row.get("rsi", 50.0) or 50.0),
            adx14=float(row.get("h4_adx", 14.0) or 14.0),
            macd_hist=0.0,
            h4_adx=float(row.get("h4_adx", 14.0) or 14.0),
            h4_regime=str(row.get("market_regime", "CHOPPY")),
            d1_trend=str(row.get("d1_trend", "neutral") or "neutral"),
            dist21=float(row.get("ema_gap", 0.0) or 0.0),
            atr14=atr,
            volatility_ratio=vol_ratio,
            hour_of_day=opened_at.hour if hasattr(opened_at, "hour") else 12,
            day_of_week=opened_at.weekday() if hasattr(opened_at, "weekday") else 0,
            sentiment_score=float(row.get("sentiment_score", 0.0) or 0.0),
            pnl=float(row.get("pnl", 0.0) or 0.0),
            rr_ratio=float(row.get("reward_risk_ratio", 1.0) or 1.0),
            market_regime=str(row.get("market_regime", "CHOPPY")),
            holding_minutes=holding_minutes,
            source=str(row.get("source", "live")),
        )
