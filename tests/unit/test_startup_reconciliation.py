"""Tests for MT5 startup position reconciliation in LiveRuntime._sync_open_positions()."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def _make_runtime():
    """Build LiveRuntime with asyncio internals bypassed."""
    with patch("autonomous_xauusd.runtime.live_runtime.asyncio"):
        from autonomous_xauusd.runtime.live_runtime import LiveRuntime
        rt = LiveRuntime.__new__(LiveRuntime)
        rt._health = MagicMock()
        rt._stop_event = MagicMock()
        rt._executor = MagicMock()
        rt._trading_system = MagicMock()
        rt._restart_count = 0
        rt._runtime_logger = MagicMock()
        return rt


def test_orphaned_positions_stored_in_runtime_state():
    """Broker positions not in DB must be stored in runtime state as orphaned."""
    rt = _make_runtime()

    db_trades = [{"broker_ticket": "111", "symbol": "XAUUSD", "side": "buy"}]
    broker_positions = [
        {"ticket": "111", "symbol": "XAUUSD", "side": "buy", "volume": 0.05},
        {"ticket": "222", "symbol": "XAUUSD", "side": "sell", "volume": 0.10},  # orphan
    ]

    rt._trading_system.memory.list_open_trades.return_value = db_trades
    rt._trading_system.engine._live_engine.sync_open_positions.return_value = broker_positions

    with patch(
        "autonomous_xauusd.settings.load_settings",
        return_value=MagicMock(symbol="XAUUSD", mode="live"),
    ):
        rt._sync_open_positions()

    call_args = rt._trading_system.memory.set_runtime_state.call_args
    assert call_args is not None
    key, payload = call_args[0]
    assert key == "orphaned_positions"
    assert payload["count"] == 1
    assert payload["positions"][0]["ticket"] == "222"


def test_no_orphans_when_all_matched():
    """No runtime state write when broker and DB positions match."""
    rt = _make_runtime()

    db_trades = [{"broker_ticket": "111", "symbol": "XAUUSD", "side": "buy"}]
    broker_positions = [{"ticket": "111", "symbol": "XAUUSD", "side": "buy", "volume": 0.05}]

    rt._trading_system.memory.list_open_trades.return_value = db_trades
    rt._trading_system.engine._live_engine.sync_open_positions.return_value = broker_positions

    with patch(
        "autonomous_xauusd.settings.load_settings",
        return_value=MagicMock(symbol="XAUUSD", mode="live"),
    ):
        rt._sync_open_positions()

    rt._trading_system.memory.set_runtime_state.assert_not_called()


def test_paper_mode_skips_broker_reconciliation():
    """In paper mode, broker reconciliation must not be called."""
    rt = _make_runtime()

    rt._trading_system.memory.list_open_trades.return_value = []

    with patch(
        "autonomous_xauusd.settings.load_settings",
        return_value=MagicMock(symbol="XAUUSD", mode="paper"),
    ):
        rt._sync_open_positions()

    rt._trading_system.engine._live_engine.sync_open_positions.assert_not_called()
    rt._trading_system.memory.set_runtime_state.assert_not_called()
