"""
XAUUSD V17 Brain Layer — ML Intelligence + V16 Strategy Engine
==============================================================
Verbeterd van V16 naar V17:
  - Gebruikt core.strategy_engine als ENIGE signaallogica
  - 6 signaaltypen (A_EMACROSS t/m F_MSS)
  - Enhanced ML training met meer features
  - Sentiment-aware signal generation
  - Betere parameter override logica
  - Pattern clustering voor setup kwaliteit
"""
from __future__ import annotations

import logging
import math
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

from core.strategy_engine import StrategyEngine, SignalResult, get_engine
from .models import SentimentScore, SignalDecision, StrategyParameters, TrainingOutcome

logger = logging.getLogger(__name__)

_REGIME_SCORE: dict[str, int] = {
    "STERK_BULL": 2,
    "BULL": 1,
    "ZWAK_BULL": 1,
    "CHOPPY": 0,
    "ZWAK_BEAR": -1,
    "BEAR": -1,
    "STERK_BEAR": -2,
}

# Vertaaltabel: V17 StrategyEngine → V16 SignalDecision compatibel
_SIDE_MAP = {"long": "buy", "short": "sell"}


def derive_parameter_overrides(
    closed_trades: pd.DataFrame,
    current_parameters: StrategyParameters,
    feature_importances: dict[str, float],
    accuracy: float,
) -> dict[str, float]:
    """
    Leert optimale parameters uit winnende trades.
    Gebruikt feature importance om te focussen op de meest impactvolle parameters.
    """
    if closed_trades.empty:
        return {}

    winners = closed_trades[closed_trades["label"] == 1].copy()
    overrides: dict[str, float] = {}

    if not winners.empty:
        # RSI parameter aanpassing
        rsi_importance = max(
            feature_importances.get("rsi_fast", 0.0),
            feature_importances.get("rsi", 0.0),
        )

        long_w = winners[winners["side"] == "buy"]
        short_w = winners[winners["side"] == "sell"]

        if not long_w.empty and rsi_importance >= 0.05:
            col = "rsi_fast" if "rsi_fast" in long_w.columns else "rsi"
            overrides["rsi_pullback_strong"] = float(np.clip(long_w[col].median(), 25.0, 40.0))
            overrides["rsi_pullback_weak"] = float(np.clip(long_w[col].median() + 5.0, 28.0, 45.0))

        if not short_w.empty and rsi_importance >= 0.05:
            col = "rsi_fast" if "rsi_fast" in short_w.columns else "rsi"
            mirror = 100 - float(short_w[col].median())
            overrides["rsi_pullback_strong"] = float(np.clip(mirror, 25.0, 40.0))

        # Take profit aanpassing op basis van winner R/R
        winner_rr = winners["reward_risk_ratio"].replace([np.inf, -np.inf], np.nan).dropna()
        if not winner_rr.empty:
            median_rr = float(winner_rr.median())
            if accuracy >= 0.57 and median_rr >= 2.0:
                overrides["take_profit_atr"] = float(
                    np.clip(current_parameters.take_profit_atr + 0.2, 2.0, 4.5)
                )
            elif accuracy < 0.50:
                overrides["take_profit_atr"] = float(
                    np.clip(current_parameters.take_profit_atr - 0.2, 2.0, 3.5)
                )

        # Beste signaaltype identificeren
        if "signal_type" in winners.columns:
            best_types = winners["signal_type"].value_counts()
            if not best_types.empty:
                overrides["_best_signal_type"] = str(best_types.index[0])

    # Risk aanpassing op basis van accuracy
    if accuracy < 0.45:
        overrides["risk_strong_regime"] = float(
            np.clip(current_parameters.risk_strong_regime * 0.80, 0.005, current_parameters.risk_strong_regime)
        )
        overrides["risk_weak_regime"] = float(
            np.clip(current_parameters.risk_weak_regime * 0.80, 0.003, current_parameters.risk_weak_regime)
        )
    elif accuracy >= 0.60:
        overrides["risk_strong_regime"] = float(
            np.clip(current_parameters.risk_strong_regime * 1.05, 0.005, 0.020)
        )

    return overrides


class IntelligenceLayer:
    """
    V17 Intelligence Layer — verbeterde ML + strategy_engine integratie.

    Signaallogica komt UITSLUITEND uit core.strategy_engine.
    Deze klasse voegt toe:
      - ML confidence scoring
      - Feature store voor training
      - Parameter override learning
      - Setup quality ranking
    """

    def __init__(self, artifact_path: Path) -> None:
        self.artifact_path = artifact_path
        self._strategy_engine: StrategyEngine = get_engine()
        self._ml_model = None
        self._ml_scaler: Optional[StandardScaler] = None
        self._ml_features: list[str] = []
        self._ml_confidence: float = 0.5  # Default confidence
        self._load_existing_model()

    def _load_existing_model(self) -> None:
        """Laad bestaand ML model als beschikbaar."""
        if self.artifact_path.exists():
            try:
                artifact = joblib.load(self.artifact_path)
                self._ml_model = artifact.get("model")
                self._ml_scaler = artifact.get("scaler")
                self._ml_features = artifact.get("feature_columns", [])
                metrics = artifact.get("metrics", {})
                self._ml_confidence = float(metrics.get("accuracy", 0.5))
                logger.info(
                    "ML model geladen: accuracy=%.1f%%, features=%d",
                    self._ml_confidence * 100, len(self._ml_features),
                )
            except Exception as e:
                logger.warning("ML model laden mislukt: %s", e)

    def prepare_market_frame(self, bars: pd.DataFrame, parameters: StrategyParameters) -> pd.DataFrame:
        """
        Verrijkt een OHLCV DataFrame via de core StrategyEngine.
        Identiek resultaat aan V16 backtest indicatoren.
        """
        if len(bars) < 50:
            return bars.iloc[0:0]

        try:
            frame = self._strategy_engine.prepare_features(bars)
        except Exception as e:
            logger.error("prepare_features mislukt: %s", e)
            return bars.iloc[0:0]

        # Extra features voor ML training
        if not frame.empty and "close" in frame.columns:
            close = frame["close"].astype(float)
            frame["volatility"] = close.pct_change().rolling(parameters.volatility_window).std().fillna(0.0)
            frame["h4_regime_score"] = frame["h4_reg"].map(_REGIME_SCORE).fillna(0).astype(float)
            frame["d1_bull"] = (frame["d1_trend"] == "bull").astype(float)

        return frame

    def generate_signal(
        self,
        frame: pd.DataFrame,
        parameters: StrategyParameters,
        symbol: str,
        timeframe: str,
        sentiment: SentimentScore | None = None,
        sentiment_threshold: float = 0.5,
        is_killzone: bool = False,
    ) -> SignalDecision | None:
        """
        Genereert een handelssignaal via de core StrategyEngine.

        Alle signaallogica (6 types) komt uit strategy_engine.
        ML confidence wordt gebruikt als extra filter en confidence score.
        Sentiment wordt doorgegeven voor boost/blokkering.
        """
        if len(frame) < 4:
            return None

        # Sentiment parameters doorgeven
        sent_score = 0.0
        sent_label = "neutral"
        if sentiment is not None:
            sent_score = float(sentiment.score)
            sent_label = str(sentiment.label)

        # Strategie configuratie uit parameters
        # adx_min (15) voor H1 apart van h4adx_min (18) — was eerder beiden h4_adx_weak
        cfg = {
            "risk_a": float(parameters.risk_strong_regime),
            "risk_b": float(parameters.risk_weak_regime) * 1.2,
            "risk_c": float(parameters.risk_weak_regime),
            "adx_min": 15.0,                                      # H1 ADX min — lager dan h4
            "h4adx_min": float(parameters.h4_adx_weak),           # H4 ADX min (18)
            "tp1_r": float(parameters.take_profit_atr) * 0.5,
            "tp2_r": float(parameters.take_profit_atr),
            "tp3_r": float(parameters.take_profit_atr) * 1.5,    # Originele waarde
            "sl_atr": float(parameters.stop_loss_atr),
            "trailing": True,
            "breakeven_r": 0.8,
            "kz_mult": 1.25,
        }

        # ML confidence score berekenen
        ml_conf = self._get_ml_confidence(frame)

        # Signaal genereren via unified engine
        signal: Optional[SignalResult] = self._strategy_engine.generate_signal(
            frame,
            cfg=cfg,
            sentiment_score=sent_score,
            sentiment_label=sent_label,
            ml_confidence=ml_conf,
            is_killzone=is_killzone,
        )

        if signal is None:
            return None

        # Vertaal naar SignalDecision (backward compatible met autonomous engine)
        bar = frame.iloc[-2]
        close = float(bar["close"]) if not math.isnan(float(bar.get("close", 0))) else signal.entry_price

        return SignalDecision(
            symbol=symbol,
            timeframe=timeframe,
            side=_SIDE_MAP.get(signal.direction, "buy"),
            opened_at=signal.timestamp or datetime.utcnow(),
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit_2,  # Gebruik TP2 als primaire TP
            market_regime=signal.h4_regime,
            reason=signal.reason,
            features={
                **signal.features,
                "signal_type": signal.signal_type,
                "priority": signal.priority,
                "confidence": signal.confidence,
                "tp1": signal.take_profit_1,
                "tp2": signal.take_profit_2,
                "tp3": signal.take_profit_3,
                "risk_pct": signal.risk_pct,
                "sentiment_score": sent_score,
                "sentiment_label": sent_label,
                "ml_confidence": ml_conf,
            },
        )

    def _get_ml_confidence(self, frame: pd.DataFrame) -> float:
        """Bereken ML confidence score op basis van huidig model."""
        if self._ml_model is None or not self._ml_features:
            return self._ml_confidence

        try:
            bar = frame.iloc[-2]
            feature_values = []
            for col in self._ml_features:
                val = bar.get(col, 0.0)
                feature_values.append(float(val) if not math.isnan(float(val or 0)) else 0.0)

            X = np.array(feature_values).reshape(1, -1)
            if self._ml_scaler:
                X = self._ml_scaler.transform(X)

            proba = self._ml_model.predict_proba(X)[0]
            return float(max(proba))  # Confidence = max klasse probabiliteit
        except Exception as e:
            logger.debug("ML confidence berekening mislukt: %s", e)
            return self._ml_confidence

    def train_model(
        self,
        closed_trades: pd.DataFrame,
        current_parameters: StrategyParameters,
    ) -> TrainingOutcome | None:
        """
        Traint het ML model op basis van historische trades.

        V17 verbetering: gebruikt GradientBoosting als ensemble
        naast RandomForest, kiest het beste model.
        """
        if closed_trades.empty or len(closed_trades) < 25:
            return None

        frame = closed_trades.copy()

        # Extended feature set voor V17
        feature_columns = [
            "rsi",
            "rsi_fast",
            "h4_regime_score",
            "d1_bull",
            "h4_adx",
            "h4_atr",
            "atr",
            "volatility",
            "reward_risk_ratio",
            "holding_minutes",
            "sentiment_score",
            "adx14",
            "macd_hist",
        ]
        available = [c for c in feature_columns if c in frame.columns]
        frame["label"] = (frame["pnl"] > 0).astype(int)
        frame = frame.dropna(subset=available)

        if frame["label"].nunique() < 2 or len(frame) < 25:
            return None

        X = frame[available]
        y = frame["label"]

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.25, random_state=42, stratify=y,
        )

        # Normalisatie
        scaler = StandardScaler()
        X_train_s = scaler.fit_transform(X_train)
        X_test_s = scaler.transform(X_test)

        # Twee modellen — kies het beste
        rf = RandomForestClassifier(
            n_estimators=250, max_depth=6,
            min_samples_leaf=2, class_weight="balanced", random_state=42,
        )
        gb = GradientBoostingClassifier(
            n_estimators=150, max_depth=4,
            learning_rate=0.05, random_state=42,
        )

        rf.fit(X_train_s, y_train)
        gb.fit(X_train_s, y_train)

        rf_acc = accuracy_score(y_test, rf.predict(X_test_s))
        gb_acc = accuracy_score(y_test, gb.predict(X_test_s))

        if gb_acc > rf_acc:
            best_model = gb
            model_name = "GradientBoosting"
        else:
            best_model = rf
            model_name = "RandomForest"

        preds = best_model.predict(X_test_s)
        accuracy = float(accuracy_score(y_test, preds))
        precision = float(precision_score(y_test, preds, zero_division=0))
        recall = float(recall_score(y_test, preds, zero_division=0))
        f1 = float(f1_score(y_test, preds, zero_division=0))

        # Feature importances
        if hasattr(best_model, "feature_importances_"):
            importances = {
                name: float(score)
                for name, score in zip(available, best_model.feature_importances_)
            }
        else:
            importances = {name: 1.0 / len(available) for name in available}

        overrides = derive_parameter_overrides(frame, current_parameters, importances, accuracy)
        self._ml_confidence = accuracy
        self._ml_model = best_model
        self._ml_scaler = scaler
        self._ml_features = available

        self.artifact_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "trained_at": datetime.utcnow().isoformat(),
                "model_type": model_name,
                "parameters": asdict(current_parameters),
                "feature_columns": available,
                "model": best_model,
                "scaler": scaler,
                "metrics": {
                    "accuracy": accuracy, "precision": precision,
                    "recall": recall, "f1_score": f1,
                },
                "feature_importances": importances,
                "parameter_overrides": overrides,
            },
            self.artifact_path,
        )

        logger.info(
            "ML model getraind (%s): accuracy=%.1f%%, precision=%.1f%%, recall=%.1f%%",
            model_name, accuracy * 100, precision * 100, recall * 100,
        )

        return TrainingOutcome(
            trained_at=datetime.utcnow(),
            sample_count=len(frame),
            accuracy=accuracy,
            precision=precision,
            recall=recall,
            f1_score=f1,
            feature_importances=importances,
            parameter_overrides=overrides,
            model_path=str(self.artifact_path),
            notes=f"V17 {model_name} model: strategy_engine geïntegreerd, {len(available)} features",
        )

    def get_setup_quality_score(self, signal: SignalResult) -> float:
        """
        Berekent een kwaliteitsscore (0-10) voor een setup op basis van:
        - Signaal prioriteit (A=6, F=1)
        - H4 regime sterkte
        - ML confidence
        - Sentiment alignment
        """
        priority_score = signal.priority / 6.0 * 4.0  # Max 4 punten

        regime_scores = {
            "STERK_BULL": 3.0, "STERK_BEAR": 3.0,
            "BULL": 2.0, "BEAR": 2.0,
            "ZWAK_BULL": 1.0, "ZWAK_BEAR": 1.0,
            "CHOPPY": 0.0,
        }
        regime_score = regime_scores.get(signal.h4_regime, 0.0)  # Max 3 punten

        ml_score = signal.confidence * 2.0  # Max 2 punten via ML

        sent_score = 0.0
        if signal.sentiment_label in ("sterk_bullish",) and signal.direction == "long":
            sent_score = 1.0
        elif signal.sentiment_label in ("sterk_bearish",) and signal.direction == "short":
            sent_score = 1.0
        elif signal.sentiment_label in ("bullish", "bearish"):
            sent_score = 0.5

        total = priority_score + regime_score + ml_score + sent_score
        return round(min(10.0, total), 2)
