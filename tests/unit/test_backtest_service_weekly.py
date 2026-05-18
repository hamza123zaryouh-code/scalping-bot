from __future__ import annotations

import pandas as pd

from backend.services.backtest_service import BacktestService
from core.strategy_engine import SignalResult


def test_build_weekly_summary_returns_eur_and_pct() -> None:
    service = BacktestService()
    trades = pd.DataFrame(
        [
            {"uit": "2026-01-05T10:00:00Z", "pnl": 1000.0},
            {"uit": "2026-01-06T10:00:00Z", "pnl": -250.0},
            {"uit": "2026-01-13T10:00:00Z", "pnl": 500.0},
        ]
    )

    weekly = service._build_weekly_summary(trades, starting=160000.0)

    assert len(weekly) == 2
    assert weekly[0].week == "2026-W02"
    assert weekly[0].pnl == 750.0
    assert weekly[0].start_equity == 160000.0
    assert weekly[0].end_equity == 160750.0
    assert weekly[0].return_pct == 0.47
    assert weekly[1].start_equity == 160750.0
    assert weekly[1].pnl == 500.0


def test_weekly_loss_filter_blocks_low_priority_setups_even_without_weekly_compound(monkeypatch) -> None:
    service = BacktestService()
    index = pd.date_range("2026-01-05 07:00", periods=130, freq="1h", tz="UTC")
    df = pd.DataFrame(
        {
            "open": 100.0,
            "high": 100.2,
            "low": 98.5,
            "close": 100.0,
            "volume": 1000.0,
        },
        index=index,
    )

    monkeypatch.setattr(service._engine, "get_session", lambda _: "premium")
    signal = SignalResult(
        direction="long",
        signal_type="D_PULLBACK",
        risk_pct=0.02,
        tp1_r=1.0,
        tp2_r=2.0,
        tp3_r=3.0,
        priority=1,
        stop_loss=99.0,
        take_profit_1=101.0,
        take_profit_2=102.0,
        take_profit_3=103.0,
    )
    monkeypatch.setattr(service._engine, "generate_signal", lambda *args, **kwargs: signal)

    trades, _ = service._run_backtest_engine(
        df,
        {
            "weekly_compound": False,
            "max_daily_loss_eur": 1_000_000.0,
            "weekly_loss_threshold": 0.01,
            "weekly_loss_block_signals": ("D_PULLBACK",),
            "cooldown_h": 0,
            "max_dag": 20,
            "sl_dag_max": 20,
        },
        starting_capital=100.0,
    )

    assert len(trades) == 1
    assert trades[0]["result"] == "SL"
