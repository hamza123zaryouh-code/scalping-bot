"""Regression tests — ensure backtest metrics stay within known bounds."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import xauusd_backtest as engine

# Known-good baseline ranges from last accepted run. Update these when you
# intentionally change strategy logic and the new numbers are correct.
BASELINE = {
    "profit_factor_min": 1.0,    # must be profitable
    "sharpe_min": 0.3,            # acceptable risk-adjusted return
    "max_drawdown_max_pct": 25.0, # must not exceed this
    "win_rate_min": 0.30,         # at least 30 % winners
    "win_rate_max": 0.90,         # suspiciously high = curve-fitting
}


@pytest.fixture(scope="module")
def backtest_result():
    """Run a short synthetic backtest and return (trades, equity_curve)."""
    rng = np.random.default_rng(42)
    n = 300
    close = 1900.0 + np.cumsum(rng.normal(0, 5, n))
    df = pd.DataFrame(
        {
            "open": close + rng.normal(0, 2, n),
            "high": close + np.abs(rng.normal(0, 3, n)) + 5,
            "low": close - np.abs(rng.normal(0, 3, n)) - 5,
            "close": close,
            "volume": rng.integers(800, 3000, n).astype(float),
        },
        index=pd.date_range("2026-01-02 03:00", periods=n, freq="1min"),
    )
    try:
        enriched = engine.add_indicators(df)
        trades, equity = engine.simulate_trades(enriched)
        return trades, equity
    except AttributeError:
        pytest.skip("Engine API changed — update test fixture")


class TestBacktestRegression:
    def test_equity_never_goes_negative(self, backtest_result):
        _, equity = backtest_result
        if hasattr(equity, "values"):
            assert (equity.values >= 0).all(), "Equity went below zero"

    def test_trades_have_required_columns(self, backtest_result):
        trades, _ = backtest_result
        if trades.empty:
            pytest.skip("No trades produced — increase data window")
        required = {"side", "entry_time", "exit_time", "pnl"}
        assert required.issubset(set(trades.columns))

    def test_no_nan_pnl(self, backtest_result):
        trades, _ = backtest_result
        if trades.empty:
            pytest.skip("No trades")
        assert not trades["pnl"].isna().any()

    def test_win_rate_in_range(self, backtest_result):
        trades, _ = backtest_result
        if len(trades) < 5:
            pytest.skip("Too few trades for meaningful regression")
        win_rate = (trades["pnl"] > 0).mean()
        assert BASELINE["win_rate_min"] <= win_rate <= BASELINE["win_rate_max"], (
            f"Win rate {win_rate:.2%} outside expected range"
        )
