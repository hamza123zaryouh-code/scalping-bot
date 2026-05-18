"""Tests for SignalService.get_latest_signal() state-key contract."""
from __future__ import annotations

import json


def _service(tmp_path):
    from backend.services.signal_service import SignalService

    svc = SignalService.__new__(SignalService)
    svc._settings = None  # not needed for get_latest_signal
    svc._state_path = tmp_path / "bot_state.json"

    # Patch the module-level STATE_PATH
    import backend.services.signal_service as mod
    mod.STATE_PATH = svc._state_path
    return svc


def test_returns_none_when_no_state_file(tmp_path):
    svc = _service(tmp_path)
    assert svc.get_latest_signal() is None


def test_reads_canonical_last_signal_keys(tmp_path):
    """Must read last_signal dict and last_signal_time — not last_trade_time."""
    svc = _service(tmp_path)
    state = {
        "last_signal_time": "2026-05-18T10:00:00+00:00",
        "last_signal": {
            "symbol": "XAUUSD",
            "timeframe": "M15",
            "side": "buy",
            "reason": "EMA_CROSS",
            "confidence": 0.82,
            "time": "2026-05-18T10:00:00+00:00",
        },
    }
    svc._state_path.write_text(json.dumps(state), encoding="utf-8")

    result = svc.get_latest_signal()

    assert result is not None
    assert result.side == "buy"
    assert result.entry_label == "LONG"
    assert result.reason == "EMA_CROSS"
    assert abs(result.confidence - 0.82) < 1e-9


def test_sell_signal_returns_short_label(tmp_path):
    svc = _service(tmp_path)
    state = {
        "last_signal_time": "2026-05-18T11:00:00+00:00",
        "last_signal": {
            "side": "sell",
            "reason": "BEARISH_BREAK",
            "confidence": 0.65,
            "time": "2026-05-18T11:00:00+00:00",
        },
    }
    svc._state_path.write_text(json.dumps(state), encoding="utf-8")

    result = svc.get_latest_signal()

    assert result is not None
    assert result.side == "sell"
    assert result.entry_label == "SHORT"


def test_legacy_keys_return_none(tmp_path):
    """Old state with last_trade_time / last_long_signal_time must not produce a signal."""
    svc = _service(tmp_path)
    state = {
        "last_trade_time": "2026-05-18T10:00:00+00:00",
        "last_long_signal_time": "2026-05-18T10:00:00+00:00",
    }
    svc._state_path.write_text(json.dumps(state), encoding="utf-8")

    result = svc.get_latest_signal()

    assert result is None
