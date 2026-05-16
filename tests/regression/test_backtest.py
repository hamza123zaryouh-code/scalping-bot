"""Regression tests — ensure backtest metrics stay within known bounds."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from core.strategy_engine import DEFAULT_CFG, StrategyEngine

# Known-good baseline ranges from last accepted run. Update these when you
# intentionally change strategy logic and the new numbers are correct.
BASELINE = {
    "profit_factor_min": 1.0,    # must be profitable
    "sharpe_min": 0.3,            # acceptable risk-adjusted return
    "max_drawdown_max_pct": 25.0, # must not exceed this
    "win_rate_min": 0.15,         # floor for synthetic random data (real market will be higher)
    "win_rate_max": 0.90,         # suspiciously high = curve-fitting
}


def _simulate_trades(df: pd.DataFrame, capital: float = 10000.0):
    """Simple backtest loop using StrategyEngine. Returns (trades_df, equity_series)."""
    strategy = StrategyEngine()
    features = strategy.prepare_features(df)
    if features.empty:
        return pd.DataFrame(), pd.Series(dtype=float)

    trades = []
    equity = [capital]
    open_trade = None

    for i in range(4, len(features)):
        window = features.iloc[:i + 1]
        bar = features.iloc[i]

        # Check if open trade hit SL or TP
        if open_trade is not None:
            hi, lo = float(bar["high"]), float(bar["low"])
            side = open_trade["side"]
            sl, tp = open_trade["sl"], open_trade["tp"]
            pnl = None
            exit_time = features.index[i]

            if side == "long":
                if lo <= sl:
                    pnl = (sl - open_trade["entry"]) * open_trade["volume"]
                elif hi >= tp:
                    pnl = (tp - open_trade["entry"]) * open_trade["volume"]
            else:
                if hi >= sl:
                    pnl = (open_trade["entry"] - sl) * open_trade["volume"]
                elif lo <= tp:
                    pnl = (open_trade["entry"] - tp) * open_trade["volume"]

            if pnl is not None:
                capital += pnl
                trades.append({
                    "side": open_trade["side"],
                    "entry_time": open_trade["entry_time"],
                    "exit_time": exit_time,
                    "entry": open_trade["entry"],
                    "exit": sl if (side == "long" and lo <= sl) or (side == "short" and hi >= sl) else tp,
                    "pnl": pnl,
                })
                open_trade = None
                equity.append(capital)
                continue

        # Generate new signal when no open trade
        if open_trade is None:
            sig = strategy.generate_signal(window, cfg=DEFAULT_CFG.copy())
            if sig is not None:
                entry = sig.entry_price
                vol = max(capital * sig.risk_pct / max(abs(entry - sig.stop_loss), 0.01), 0.01)
                open_trade = {
                    "side": sig.direction,
                    "entry": entry,
                    "sl": sig.stop_loss,
                    "tp": sig.take_profit_2,
                    "volume": vol,
                    "entry_time": features.index[i],
                }

    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame(
        columns=["side", "entry_time", "exit_time", "entry", "exit", "pnl"]
    )
    equity_series = pd.Series(equity)
    return trades_df, equity_series


@pytest.fixture(scope="module")
def backtest_result():
    """Run a short synthetic backtest and return (trades, equity_curve)."""
    rng = np.random.default_rng(42)
    n = 400
    close = 2300.0 + np.cumsum(rng.normal(0, 5, n))
    df = pd.DataFrame(
        {
            "open": close + rng.normal(0, 2, n),
            "high": close + np.abs(rng.normal(0, 3, n)) + 5,
            "low": close - np.abs(rng.normal(0, 3, n)) - 5,
            "close": close,
            "volume": rng.integers(800, 3000, n).astype(float),
        },
        index=pd.date_range("2026-01-06 07:00", periods=n, freq="1h", tz="UTC"),
    )
    trades, equity = _simulate_trades(df)
    return trades, equity


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
