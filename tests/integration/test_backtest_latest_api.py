from __future__ import annotations

from backend.api.schemas.backtest import BacktestMetrics, BacktestResult, WeeklySummary


def test_latest_backtest_endpoint_returns_weekly_summary(api_client, monkeypatch):
    from backend.api.routes import backtest as backtest_route

    monkeypatch.setattr(
        backtest_route._service,
        "get_latest_result",
        lambda: BacktestResult(
            task_id="bt-123",
            metrics=BacktestMetrics(
                total_trades=12,
                win_rate=0.58,
                profit_factor=1.9,
                sharpe_ratio=0.8,
                max_drawdown_pct=3.2,
                total_return_pct=6.4,
                avg_win=200.0,
                avg_loss=-120.0,
                expectancy=45.0,
                calmar_ratio=2.0,
                ftmo_passed=True,
                challenge_days=18,
            ),
            trades=[],
            equity_curve=[],
            monthly_summary=[],
            weekly_summary=[
                WeeklySummary(
                    week="2026-W02",
                    week_start="2026-01-05",
                    trades=4,
                    pnl=750.0,
                    return_pct=0.47,
                    start_equity=160000.0,
                    end_equity=160750.0,
                    win_rate=0.5,
                )
            ],
            chart_path="",
        ),
    )

    response = api_client.get("/api/v1/backtest/latest")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["task_id"] == "bt-123"
    assert data["weekly_summary"][0]["pnl"] == 750.0
    assert data["weekly_summary"][0]["return_pct"] == 0.47
