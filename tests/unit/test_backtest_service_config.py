from __future__ import annotations

from datetime import date

from backend.api.schemas.backtest import BacktestRequest
from backend.services.backtest_service import BacktestService


def test_build_cfg_uses_live_strategy_config_as_base(monkeypatch) -> None:
    service = BacktestService()
    monkeypatch.setattr(
        service._strategy_config,
        "get_strategy_cfg",
        lambda: {
            "risk_a": 0.015,
            "reset_weeks": 3,
            "max_daily_loss_eur": 6000.0,
        },
    )

    req = BacktestRequest(start_date=date(2026, 1, 1), end_date=date(2026, 1, 2))
    cfg = service._build_cfg(req)

    assert cfg["risk_a"] == 0.015
    assert cfg["reset_weeks"] == 3
    assert cfg["max_daily_loss_eur"] == 6000.0


def test_build_cfg_allows_request_overrides_on_top_of_live_config(monkeypatch) -> None:
    service = BacktestService()
    monkeypatch.setattr(
        service._strategy_config,
        "get_strategy_cfg",
        lambda: {
            "risk_a": 0.015,
            "reset_weeks": 3,
        },
    )

    req = BacktestRequest(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2),
        strategy_params={"risk_a": 0.02, "cooldown_h": 1.5},
    )
    cfg = service._build_cfg(req)

    assert cfg["risk_a"] == 0.02
    assert cfg["reset_weeks"] == 3
    assert cfg["cooldown_h"] == 1.5
