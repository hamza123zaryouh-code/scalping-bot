"""Tests for balance/equity 0.0 handling in TelegramService.get_status_overview()."""
from __future__ import annotations

from unittest.mock import MagicMock


def _service(state: dict, runtime: dict, starting_capital: float = 160_000.0):
    """Build a TelegramService with all dependencies stubbed."""
    from backend.services.telegram_service import TelegramService

    svc = TelegramService.__new__(TelegramService)
    svc._settings = MagicMock()
    svc._settings.starting_capital = starting_capital
    svc._memory = MagicMock()
    svc._risk = MagicMock()
    svc._signals = MagicMock()
    svc._backtests = MagicMock()

    svc._memory.get_bot_control_state.return_value = {"bot_active": True}
    svc._memory.get_runtime_state.return_value = runtime

    # Stub _load_state, _trade_history, _period_pnl, _ftmo_snapshot, _money
    svc._load_state = MagicMock(return_value=state)
    svc._trade_history = MagicMock(return_value=[])
    svc._period_pnl = MagicMock(return_value=0.0)
    svc._ftmo_snapshot = MagicMock(return_value={"status": "OK", "can_trade": True})
    svc._money = lambda v: f"${float(v):,.2f}"

    return svc


def test_zero_balance_is_preserved():
    """balance=0.0 from state must NOT be replaced by starting_capital."""
    svc = _service(
        state={"balance": 0.0, "equity": 0.0, "open_positions": []},
        runtime={},
        starting_capital=160_000.0,
    )
    result = svc.get_status_overview()

    assert result["balance"] == 0.0, f"Expected 0.0, got {result['balance']}"
    assert result["equity"] == 0.0, f"Expected 0.0, got {result['equity']}"


def test_zero_equity_from_runtime_is_preserved():
    """equity=0.0 from runtime must NOT be replaced by account value."""
    svc = _service(
        state={},  # no balance/equity in state
        runtime={"balance": 0.0, "equity": 0.0},
        starting_capital=160_000.0,
    )
    result = svc.get_status_overview()

    assert result["balance"] == 0.0
    assert result["equity"] == 0.0


def test_missing_balance_falls_back_to_starting_capital():
    """When both state and runtime have no balance, starting_capital is used."""
    svc = _service(state={}, runtime={}, starting_capital=160_000.0)
    result = svc.get_status_overview()

    assert result["balance"] == 160_000.0


def test_state_balance_takes_priority_over_runtime():
    """State balance must be preferred over runtime balance."""
    svc = _service(
        state={"balance": 50_000.0, "equity": 49_000.0, "open_positions": []},
        runtime={"balance": 99_000.0, "equity": 98_000.0},
        starting_capital=160_000.0,
    )
    result = svc.get_status_overview()

    assert result["balance"] == 50_000.0
    assert result["equity"] == 49_000.0
