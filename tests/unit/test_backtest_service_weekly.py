from __future__ import annotations

import pandas as pd

from backend.services.backtest_service import BacktestService


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
