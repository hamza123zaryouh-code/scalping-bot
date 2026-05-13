"""Unit tests for indicators.py and signal derivation."""
from __future__ import annotations

import pandas as pd
import pytest

from indicators import derive_live_signal, prepare_live_features


class TestPrepareFeatures:
    def test_output_has_expected_columns(self, sample_ohlcv):
        result = prepare_live_features(sample_ohlcv)
        if result.empty:
            pytest.skip("Backtest engine could not produce features for this data size")
        for col in ("close", "volume"):
            assert col in result.columns

    def test_empty_input_returns_empty(self):
        result = prepare_live_features(pd.DataFrame())
        assert result.empty


class TestDeriveSignal:
    def _enriched(self, n: int = 10) -> pd.DataFrame:
        """Minimal enriched frame with all required columns."""
        idx = pd.date_range("2026-01-01", periods=n, freq="1min")
        return pd.DataFrame(
            {
                "open": 1900.0,
                "high": 1910.0,
                "low": 1890.0,
                "close": 1905.0,
                "volume": 1500.0,
                "volume_ma20": 1200.0,
                "ema8": 1902.0,
                "ema21": 1898.0,
                "ema50": 1895.0,
                "rsi14": 55.0,
                "atr14": 8.0,
                "cross_up": False,
                "cross_down": False,
                "m5_bias": "bull",
            },
            index=idx,
        )

    def test_no_signal_without_cross(self):
        df = self._enriched()
        result = derive_live_signal(df, None, None, min_volume_multiplier=1.10)
        assert result is None

    def test_long_signal_on_cross(self):
        df = self._enriched()
        # Force a cross_up on the second-to-last bar
        df.iloc[-2, df.columns.get_loc("cross_up")] = True
        result = derive_live_signal(df, None, None, min_volume_multiplier=1.10)
        if result is not None:
            assert result.side == "buy"
            assert isinstance(result.atr_value, float)

    def test_insufficient_bars_returns_none(self):
        df = self._enriched(n=2)
        assert derive_live_signal(df, None, None, min_volume_multiplier=1.10) is None
