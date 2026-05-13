from __future__ import annotations

import math
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score
from sklearn.model_selection import train_test_split

from .models import SentimentScore, SignalDecision, StrategyParameters, TrainingOutcome

_REGIME_SCORE: dict[str, int] = {
    "STERK_BULL": 2,
    "ZWAK_BULL": 1,
    "CHOPPY": 0,
    "ZWAK_BEAR": -1,
    "STERK_BEAR": -2,
}


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0).rolling(period).mean()
    loss = (-delta).clip(lower=0.0).rolling(period).mean().replace(0.0, np.nan)
    return (100.0 - 100.0 / (1.0 + gain / loss)).fillna(50.0)


def _atr_ewm(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr = pd.concat(
        [(high - low).abs(), (high - close.shift(1)).abs(), (low - close.shift(1)).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(com=period - 1, adjust=False).mean()


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    up = high.diff()
    down = -low.diff()
    plus_dm = ((up > down) & (up > 0)) * up
    minus_dm = ((down > up) & (down > 0)) * down
    atr = _atr_ewm(high, low, close, period).replace(0, np.nan)
    plus_di = 100 * plus_dm.ewm(com=period - 1, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(com=period - 1, adjust=False).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(com=period - 1, adjust=False).mean().fillna(0)


def _h4_regime(e21: float, e50: float, e200: float, adx: float, slope: float, adx_strong: float, adx_weak: float) -> str:
    bull = e21 > e50
    bear = e21 < e50
    if bull and adx >= adx_strong and slope > 0 and e50 > e200:
        return "STERK_BULL"
    if bull and adx >= adx_weak:
        return "ZWAK_BULL"
    if bear and adx >= adx_strong and slope < 0 and e50 < e200:
        return "STERK_BEAR"
    if bear and adx >= adx_weak:
        return "ZWAK_BEAR"
    return "CHOPPY"


def derive_parameter_overrides(
    closed_trades: pd.DataFrame,
    current_parameters: StrategyParameters,
    feature_importances: dict[str, float],
    accuracy: float,
) -> dict[str, float]:
    if closed_trades.empty:
        return {}

    winners = closed_trades[closed_trades["label"] == 1].copy()
    overrides: dict[str, float] = {}

    if not winners.empty:
        long_w = winners[winners["side"] == "buy"]
        short_w = winners[winners["side"] == "sell"]
        rsi_importance = feature_importances.get("rsi_fast", feature_importances.get("rsi", 0.0))

        if not long_w.empty and rsi_importance >= 0.05:
            col = "rsi_fast" if "rsi_fast" in long_w.columns else "rsi"
            overrides["rsi_pullback_strong"] = float(np.clip(long_w[col].median(), 25.0, 40.0))
            overrides["rsi_pullback_weak"] = float(np.clip(long_w[col].median() + 5.0, 28.0, 45.0))
        if not short_w.empty and rsi_importance >= 0.05:
            col = "rsi_fast" if "rsi_fast" in short_w.columns else "rsi"
            mirror = 100 - float(short_w[col].median())
            overrides["rsi_pullback_strong"] = float(np.clip(mirror, 25.0, 40.0))

        winner_rr = winners["reward_risk_ratio"].replace([np.inf, -np.inf], np.nan).dropna()
        if not winner_rr.empty:
            median_rr = float(winner_rr.median())
            if accuracy >= 0.57 and median_rr >= 2.0:
                overrides["take_profit_atr"] = float(np.clip(current_parameters.take_profit_atr + 0.2, 2.0, 4.5))
            elif accuracy < 0.50:
                overrides["take_profit_atr"] = float(np.clip(current_parameters.take_profit_atr - 0.2, 2.0, 3.5))

    if accuracy < 0.45:
        overrides["risk_strong_regime"] = float(np.clip(current_parameters.risk_strong_regime * 0.80, 0.005, current_parameters.risk_strong_regime))
        overrides["risk_weak_regime"] = float(np.clip(current_parameters.risk_weak_regime * 0.80, 0.003, current_parameters.risk_weak_regime))
    elif accuracy >= 0.60:
        overrides["risk_strong_regime"] = float(np.clip(current_parameters.risk_strong_regime * 1.05, 0.005, 0.020))

    return overrides


class IntelligenceLayer:
    def __init__(self, artifact_path: Path) -> None:
        self.artifact_path = artifact_path

    def prepare_market_frame(self, bars: pd.DataFrame, parameters: StrategyParameters) -> pd.DataFrame:
        frame = bars.copy()
        if len(frame) < 50:
            return frame.iloc[0:0]

        close = frame["close"].astype(float)
        high = frame["high"].astype(float)
        low = frame["low"].astype(float)

        frame["rsi"] = _rsi(close, parameters.rsi_period)
        frame["rsi_fast"] = _rsi(close, parameters.rsi_fast_period)
        frame["atr"] = _atr_ewm(high, low, close, parameters.atr_period)
        frame["volatility"] = close.pct_change().rolling(parameters.volatility_window).std().fillna(0.0)

        # ── H4 layer ──────────────────────────────────────────────────────────
        h4 = frame[["open", "high", "low", "close"]].resample("4h").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last"}
        ).dropna()

        if len(h4) >= 15:
            h4["e21"] = _ema(h4["close"], 21)
            h4["e50"] = _ema(h4["close"], 50)
            h4["e200"] = _ema(h4["close"], 200)
            h4["slope"] = h4["e21"] - h4["e21"].shift(3)
            h4["adx"] = _adx(h4["high"], h4["low"], h4["close"], 14)
            h4["atr_h4"] = _atr_ewm(h4["high"], h4["low"], h4["close"], 14)

            h4["regime"] = h4.apply(
                lambda r: _h4_regime(
                    r["e21"], r["e50"], r["e200"], r["adx"], r["slope"],
                    parameters.h4_adx_strong, parameters.h4_adx_weak,
                ),
                axis=1,
            )

            frame["h4_regime"] = h4["regime"].reindex(frame.index, method="ffill").fillna("CHOPPY")
            frame["h4_atr"] = h4["atr_h4"].reindex(frame.index, method="ffill").bfill()
            frame["h4_adx"] = h4["adx"].reindex(frame.index, method="ffill").fillna(0.0)
        else:
            frame["h4_regime"] = "CHOPPY"
            frame["h4_atr"] = frame["atr"]
            frame["h4_adx"] = 0.0

        # ── D1 layer ──────────────────────────────────────────────────────────
        d1 = frame[["open", "high", "low", "close"]].resample("1D").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last"}
        ).dropna()

        if len(d1) >= 10:
            d1["e50"] = _ema(d1["close"], 50)
            d1["trend"] = (d1["close"] > d1["e50"]).map({True: "bull", False: "bear"})
            frame["d1_trend"] = d1["trend"].reindex(frame.index, method="ffill").fillna("bull")
        else:
            frame["d1_trend"] = "bull"

        frame["h4_regime_score"] = frame["h4_regime"].map(_REGIME_SCORE).fillna(0).astype(float)
        frame["d1_bull"] = (frame["d1_trend"] == "bull").astype(float)

        return frame.dropna(subset=["rsi", "atr", "h4_atr", "h4_regime"]).copy()

    def generate_signal(
        self,
        frame: pd.DataFrame,
        parameters: StrategyParameters,
        symbol: str,
        timeframe: str,
        sentiment: SentimentScore | None = None,
        sentiment_threshold: float = 0.5,
    ) -> SignalDecision | None:
        if len(frame) < 4:
            return None

        bar = frame.iloc[-2]
        regime = str(bar.get("h4_regime", "CHOPPY"))
        d1_trend = str(bar.get("d1_trend", "bull"))
        rsi_fast = float(bar.get("rsi_fast", 50.0))
        atr_h4 = float(bar.get("h4_atr", bar["atr"]))
        close = float(bar["close"])

        if not math.isfinite(atr_h4) or atr_h4 <= 0:
            return None

        if regime == "CHOPPY":
            return None

        side: str | None = None
        sig_type: str | None = None

        if regime == "STERK_BULL" and d1_trend == "bull" and rsi_fast < parameters.rsi_pullback_strong:
            side, sig_type = "buy", "STERK_LONG"
        elif regime == "ZWAK_BULL" and d1_trend == "bull" and rsi_fast < parameters.rsi_pullback_weak:
            side, sig_type = "buy", "ZWAK_LONG"
        elif regime == "STERK_BEAR" and d1_trend == "bear" and rsi_fast > (100 - parameters.rsi_pullback_strong):
            side, sig_type = "sell", "STERK_SHORT"
        elif regime == "ZWAK_BEAR" and d1_trend == "bear" and rsi_fast > (100 - parameters.rsi_pullback_weak):
            side, sig_type = "sell", "ZWAK_SHORT"

        if side is None:
            return None

        # Sentiment filter: blokkeer alleen bij sterke tegenstrijdigheid (sterk_bearish vs long)
        # Zwakke bias (bullish/bearish) blokkeert niet — alleen sterk_bearish/sterk_bullish
        if sentiment is not None:
            if side == "buy" and sentiment.label == "sterk_bearish":
                return None
            if side == "sell" and sentiment.label == "sterk_bullish":
                return None

        direction = 1 if side == "buy" else -1
        sl_dist = parameters.stop_loss_atr * atr_h4
        tp_dist = parameters.take_profit_atr * atr_h4

        features = {
            "rsi": float(bar["rsi"]),
            "rsi_fast": rsi_fast,
            "h4_regime": regime,
            "h4_regime_score": float(bar.get("h4_regime_score", 0.0)),
            "h4_adx": float(bar.get("h4_adx", 0.0)),
            "h4_atr": atr_h4,
            "d1_trend": d1_trend,
            "d1_bull": float(bar.get("d1_bull", 1.0)),
            "atr": float(bar["atr"]),
            "volatility": float(bar.get("volatility", 0.0)),
            "signal_type": sig_type,
        }

        return SignalDecision(
            symbol=symbol,
            timeframe=timeframe,
            side=side,
            opened_at=pd.Timestamp(bar.name).to_pydatetime(),
            entry_price=close,
            stop_loss=close - direction * sl_dist,
            take_profit=close + direction * tp_dist,
            market_regime=regime,
            reason=f"{sig_type}: H4={regime} D1={d1_trend} RSI5={rsi_fast:.1f} ATRh4={atr_h4:.1f}",
            features=features,
        )

    def train_model(self, closed_trades: pd.DataFrame, current_parameters: StrategyParameters) -> TrainingOutcome | None:
        if closed_trades.empty or len(closed_trades) < 25:
            return None

        frame = closed_trades.copy()
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

        model = RandomForestClassifier(
            n_estimators=250,
            max_depth=6,
            min_samples_leaf=2,
            class_weight="balanced",
            random_state=42,
        )
        model.fit(X_train, y_train)

        preds = model.predict(X_test)
        accuracy = float(accuracy_score(y_test, preds))
        precision = float(precision_score(y_test, preds, zero_division=0))
        recall = float(recall_score(y_test, preds, zero_division=0))
        f1 = float(f1_score(y_test, preds, zero_division=0))
        importances = {name: float(score) for name, score in zip(available, model.feature_importances_)}
        overrides = derive_parameter_overrides(frame, current_parameters, importances, accuracy)

        self.artifact_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "trained_at": datetime.utcnow().isoformat(),
                "parameters": asdict(current_parameters),
                "feature_columns": available,
                "model": model,
                "metrics": {"accuracy": accuracy, "precision": precision, "recall": recall, "f1_score": f1},
                "feature_importances": importances,
                "parameter_overrides": overrides,
            },
            self.artifact_path,
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
            notes="Weekly feedback loop: XAUUSD v9 multi-timeframe parameters updated.",
        )
