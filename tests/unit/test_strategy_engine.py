"""Unit tests for core/strategy_engine.py (V17 unified signal engine)."""
from __future__ import annotations

import pandas as pd
import pytest

from core.strategy_engine import DEFAULT_CFG, SignalResult, StrategyEngine, get_engine


def _make_ohlcv(n: int = 200, base_price: float = 2300.0) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=n, freq="1h")
    import numpy as np
    rng = np.random.default_rng(42)
    closes = base_price + rng.normal(0, 5, n).cumsum()
    return pd.DataFrame(
        {
            "open": closes - 1,
            "high": closes + 3,
            "low": closes - 3,
            "close": closes,
            "volume": rng.uniform(800, 1500, n),
            "spread": 0.3,
        },
        index=idx,
    )


class TestDefaultConfig:
    def test_risk_hierarchy(self):
        assert DEFAULT_CFG["risk_a"] > DEFAULT_CFG["risk_b"] > DEFAULT_CFG["risk_c"]

    def test_tp_hierarchy(self):
        assert DEFAULT_CFG["tp1_r"] < DEFAULT_CFG["tp2_r"] < DEFAULT_CFG["tp3_r"]

    def test_sl_atr_positive(self):
        assert DEFAULT_CFG["sl_atr"] > 0


class TestGetEngine:
    def test_returns_engine_instance(self):
        engine = get_engine()
        assert isinstance(engine, StrategyEngine)

    def test_singleton_behavior(self):
        e1 = get_engine()
        e2 = get_engine()
        assert e1 is e2

    def test_custom_cfg_merged(self):
        engine = get_engine({"risk_a": 0.006})
        assert engine.cfg["risk_a"] == pytest.approx(0.006)


class TestPrepareFeatures:
    def test_output_has_core_columns(self):
        engine = get_engine()
        df = _make_ohlcv(200)
        result = engine.prepare_features(df)
        if result.empty:
            pytest.skip("Insufficient data for feature preparation")
        for col in ("close", "high", "low", "open", "volume"):
            assert col in result.columns

    def test_empty_input_returns_empty(self):
        engine = get_engine()
        result = engine.prepare_features(pd.DataFrame())
        assert result.empty

    def test_small_input_returns_empty(self):
        engine = get_engine()
        result = engine.prepare_features(_make_ohlcv(5))
        assert result.empty


class TestGenerateSignal:
    def test_returns_none_or_signal_result(self):
        engine = get_engine()
        df = _make_ohlcv(200)
        features = engine.prepare_features(df)
        if features.empty:
            pytest.skip("Insufficient data")
        result = engine.generate_signal(features)
        assert result is None or isinstance(result, SignalResult)

    def test_signal_direction_valid(self):
        engine = get_engine()
        df = _make_ohlcv(300)
        features = engine.prepare_features(df)
        if features.empty:
            pytest.skip("Insufficient data")
        signal = engine.generate_signal(features)
        if signal is not None:
            assert signal.direction in ("long", "short")

    def test_signal_type_valid(self):
        engine = get_engine()
        df = _make_ohlcv(300)
        features = engine.prepare_features(df)
        if features.empty:
            pytest.skip("Insufficient data")
        signal = engine.generate_signal(features)
        valid_types = {"A_EMACROSS", "B_MACDCROSS", "C_MOMENTUM", "D_PULLBACK", "E_BOS", "F_MSS"}
        if signal is not None:
            assert signal.signal_type in valid_types

    def test_signal_risk_within_bounds(self):
        engine = get_engine()
        df = _make_ohlcv(300)
        features = engine.prepare_features(df)
        if features.empty:
            pytest.skip("Insufficient data")
        signal = engine.generate_signal(features)
        if signal is not None:
            assert 0 < signal.risk_pct <= 0.02
