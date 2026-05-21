from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_snapshot_messages_reuses_single_bot_state_read(monkeypatch):
    from backend.services import ws_stream_service

    service = ws_stream_service.WsStreamService()
    calls = {"count": 0}

    def fake_read_bot_state():
        calls["count"] += 1
        return {
            "balance": 160000.0 + calls["count"],
            "equity": 159500.0 + calls["count"],
            "day_start_equity": 160200.0,
            "open_positions": [
                {"ticket": 1, "symbol": "XAUUSD", "side": "buy", "volume": 0.1, "profit": 42.5}
            ],
            "last_signal_time": "2026-05-18T10:00:00+00:00",
            "last_signal": {
                "symbol": "XAUUSD",
                "timeframe": "M15",
                "side": "buy",
                "reason": "breakout",
                "confidence": 0.82,
            },
            "updated_at": "2026-05-18T10:00:05+00:00",
        }

    monkeypatch.setattr(ws_stream_service, "_read_bot_state", fake_read_bot_state)

    messages = await service.snapshot_messages({"equity", "positions", "trades"})
    by_type = {message["type"]: message["payload"] for message in messages}

    assert calls["count"] == 1
    assert by_type["equity.update"]["equity"] == 159501.0
    assert by_type["positions.update"]["count"] == 1
    assert by_type["signal.detected"]["reason"] == "breakout"
