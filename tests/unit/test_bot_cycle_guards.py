"""Tests for production-critical guards in AutonomousTradingSystem._run_cycle()."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def _make_system():
    """Build an AutonomousTradingSystem with all heavy dependencies stubbed out."""
    with (
        patch("autonomous_xauusd.main.MemoryLayer") as MockMemory,
        patch("autonomous_xauusd.main.IntelligenceLayer"),
        patch("autonomous_xauusd.main.DataExecutionLayer"),
        patch("autonomous_xauusd.main.SentimentEngine"),
        patch("autonomous_xauusd.main.get_circuit_breaker"),
        patch("autonomous_xauusd.main.SessionEngine"),
        patch("autonomous_xauusd.main.StrategyConfigManager"),
        patch("autonomous_xauusd.main.LiveNewsEngine"),
        patch("autonomous_xauusd.main.NewsGuard"),
        patch("autonomous_xauusd.main.PatternMemoryEngine"),
        patch("autonomous_xauusd.main.get_ftmo_guard"),
        patch("autonomous_xauusd.main.TelegramControlLayer"),
        patch("autonomous_xauusd.main.load_settings"),
    ):
        from autonomous_xauusd.main import AutonomousTradingSystem

        memory_instance = MockMemory.return_value
        memory_instance.initialize.return_value = None
        memory_instance.load_strategy_parameters.return_value = MagicMock()
        memory_instance.save_strategy_parameters.return_value = None
        memory_instance.set_bot_control_state.return_value = None
        memory_instance.get_runtime_state.return_value = {}
        memory_instance.set_runtime_state.return_value = None

        system = AutonomousTradingSystem.__new__(AutonomousTradingSystem)
        system.memory = memory_instance
        system.consecutive_errors = 0
        system.stop_requested = False
        system.last_processed_bar = None
        system.engine = MagicMock()
        system.brain = MagicMock()
        system.sentiment = MagicMock()
        system.circuit_breaker = MagicMock()
        system.session_engine = MagicMock()
        system.config_manager = MagicMock()
        system._news_engine = MagicMock()
        system._news_guard = MagicMock()
        system._pattern_memory = MagicMock()
        system._ftmo_guard = MagicMock()
        system.telegram = MagicMock()
        system.settings = MagicMock()
        system.parameters = MagicMock()

        return system


def test_run_cycle_does_not_trade_when_bot_inactive():
    """_run_cycle() must abort immediately when bot_active=False — no signals, no trades."""
    system = _make_system()

    system.memory.get_bot_control_state.return_value = {
        "bot_active": False,
        "trading_paused": False,
        "emergency_stop": False,
        "signals_enabled": True,
    }

    system._run_cycle()

    # Engine must NOT have been called for signals or trades
    system.engine.fetch_recent_candles.assert_not_called()
    system.brain.generate_signal.assert_not_called()
    system.engine.execute_trade.assert_not_called()


def test_run_cycle_proceeds_when_bot_active():
    """_run_cycle() must proceed past the bot_active gate when bot_active=True."""
    system = _make_system()

    system.memory.get_bot_control_state.return_value = {
        "bot_active": True,
        "trading_paused": False,
        "emergency_stop": False,
        "signals_enabled": True,
    }

    # Simulate a non-trading session so the cycle returns early after the gate
    session_info = MagicMock()
    session_info.is_valid_for_trading = False
    system.session_engine.get_session_info.return_value = session_info

    system._run_cycle()

    # The cycle got past bot_active guard and called session engine
    system.session_engine.get_session_info.assert_called_once()
    system.engine.execute_trade.assert_not_called()


def test_run_cycle_does_not_trade_when_trading_paused():
    """_run_cycle() must abort before any market I/O when trading_paused=True."""
    system = _make_system()

    system.memory.get_bot_control_state.return_value = {
        "bot_active": True,
        "trading_paused": True,
        "emergency_stop": False,
        "signals_enabled": True,
    }

    system._run_cycle()

    # No market data fetched, no signals, no trades
    system.engine.fetch_recent_candles.assert_not_called()
    system.brain.generate_signal.assert_not_called()
    system.engine.execute_trade.assert_not_called()


def test_run_cycle_does_not_trade_when_emergency_stop():
    """_run_cycle() must abort before any market I/O when emergency_stop=True."""
    system = _make_system()

    system.memory.get_bot_control_state.return_value = {
        "bot_active": True,
        "trading_paused": False,
        "emergency_stop": True,
        "signals_enabled": True,
    }

    system._run_cycle()

    # No market data fetched, no signals, no trades
    system.engine.fetch_recent_candles.assert_not_called()
    system.brain.generate_signal.assert_not_called()
    system.engine.execute_trade.assert_not_called()


def test_run_cycle_emergency_stop_takes_priority_over_active_session():
    """emergency_stop must block trading even when the session would allow it."""
    system = _make_system()

    system.memory.get_bot_control_state.return_value = {
        "bot_active": True,
        "trading_paused": False,
        "emergency_stop": True,
        "signals_enabled": True,
    }
    # Even if the session engine would say "valid", the guard must fire first
    session_info = MagicMock()
    session_info.is_valid_for_trading = True
    system.session_engine.get_session_info.return_value = session_info

    system._run_cycle()

    # Session engine must NOT be reached — emergency_stop fires before it
    system.session_engine.get_session_info.assert_not_called()
    system.engine.execute_trade.assert_not_called()
