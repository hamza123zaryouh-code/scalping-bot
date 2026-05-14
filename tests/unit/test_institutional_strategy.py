from __future__ import annotations

from pathlib import Path

import pandas as pd

from institutional_strategy import ExportMarketLoader, InstitutionalResearchEngine, StrategyConfig


def test_export_loader_reconstructs_timestamps() -> None:
    market = ExportMarketLoader(Path("exports/latest/data")).load()
    assert isinstance(market.index, pd.DatetimeIndex)
    assert market.index.is_monotonic_increasing
    assert {"open", "high", "low", "close", "volume", "spread", "session"}.issubset(market.columns)


def test_research_engine_produces_summary() -> None:
    market = ExportMarketLoader(Path("exports/latest/data")).load()
    engine = InstitutionalResearchEngine(market)
    result = engine.run_backtest(
        StrategyConfig(
            name="unit_probe",
            min_quality_score=4.0,
            min_h1_atr_pct=25.0,
            min_volume_ratio=0.80,
            max_spread=2.30,
            stop_atr_multiple=1.10,
            entry_confirmation_body=0.06,
        )
    )
    summary = result["summary"]
    assert "profit_factor" in summary
    assert "max_drawdown_pct" in summary
    assert "total_trades" in summary
    assert summary["starting_capital"] == 160000.0
