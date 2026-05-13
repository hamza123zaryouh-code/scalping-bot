from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

import xauusd_backtest as baseline


@dataclass(frozen=True)
class LiveSignal:
    side: str
    entry_label: str
    trigger_time: pd.Timestamp
    atr_value: float
    reference_price: float
    reason: str


def prepare_live_features(m1_raw: pd.DataFrame) -> pd.DataFrame:
    if m1_raw.empty:
        return pd.DataFrame()
    m1 = baseline.add_indicators(m1_raw.copy())
    m5 = baseline.make_m5_bars(m1_raw.copy())
    return baseline.apply_m5_bias(m1, m5)


def derive_live_signal(
    enriched: pd.DataFrame,
    last_long_signal_time: pd.Timestamp | None,
    last_short_signal_time: pd.Timestamp | None,
    min_volume_multiplier: float,
    adx_min_strength: float = 22.0,
) -> LiveSignal | None:
    if len(enriched) < 4:
        return None

    signal_bar = enriched.iloc[-2]
    prior_bar = enriched.iloc[-3]

    # ADX filter: only trade when market is actually trending
    adx_value = baseline.safe_float(signal_bar.get("adx14", 0.0))
    if adx_value < adx_min_strength:
        return None

    recent_long_cross = bool(signal_bar["cross_up"] or prior_bar["cross_up"])
    recent_short_cross = bool(signal_bar["cross_down"] or prior_bar["cross_down"])
    long_cross_time = signal_bar.name if bool(signal_bar["cross_up"]) else prior_bar.name
    short_cross_time = signal_bar.name if bool(signal_bar["cross_down"]) else prior_bar.name

    rsi = baseline.safe_float(signal_bar["rsi14"])
    # Tightened RSI zones: avoids borderline overbought/oversold entries
    long_entry = (
        signal_bar["m5_bias"] == "bull"
        and recent_long_cross
        and baseline.safe_float(signal_bar["close"]) > baseline.safe_float(signal_bar["ema50"])
        and 53 <= rsi <= 67
        and baseline.safe_float(signal_bar["volume"]) > baseline.safe_float(signal_bar["volume_ma20"]) * min_volume_multiplier
    )
    short_entry = (
        signal_bar["m5_bias"] == "bear"
        and recent_short_cross
        and baseline.safe_float(signal_bar["close"]) < baseline.safe_float(signal_bar["ema50"])
        and 33 <= rsi <= 47
        and baseline.safe_float(signal_bar["volume"]) > baseline.safe_float(signal_bar["volume_ma20"]) * min_volume_multiplier
    )

    if long_entry and (last_long_signal_time is None or pd.Timestamp(long_cross_time) != pd.Timestamp(last_long_signal_time)):
        return LiveSignal(
            side="buy",
            entry_label="LONG",
            trigger_time=pd.Timestamp(long_cross_time),
            atr_value=baseline.safe_float(signal_bar["atr14"]),
            reference_price=baseline.safe_float(signal_bar["close"]),
            reason=f"M5 bull + EMA cross-up + EMA50 + RSI {rsi:.0f} + ADX {adx_value:.0f} + volume",
        )

    if short_entry and (last_short_signal_time is None or pd.Timestamp(short_cross_time) != pd.Timestamp(last_short_signal_time)):
        return LiveSignal(
            side="sell",
            entry_label="SHORT",
            trigger_time=pd.Timestamp(short_cross_time),
            atr_value=baseline.safe_float(signal_bar["atr14"]),
            reference_price=baseline.safe_float(signal_bar["close"]),
            reason=f"M5 bear + EMA cross-down + EMA50 + RSI {rsi:.0f} + ADX {adx_value:.0f} + volume",
        )

    return None
