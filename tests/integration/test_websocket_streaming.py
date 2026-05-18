from __future__ import annotations

import json


def _receive_until_types(websocket, expected_types: set[str], max_messages: int = 12) -> dict[str, dict]:
    seen: dict[str, dict] = {}
    for _ in range(max_messages):
        message = websocket.receive_json()
        message_type = message.get("type")
        if isinstance(message_type, str):
            seen[message_type] = message
        if expected_types.issubset(seen):
            return seen
    raise AssertionError(f"Did not receive all expected websocket messages: {sorted(expected_types - set(seen))}")


def test_websocket_sends_initial_bot_snapshots(api_client, issued_token, monkeypatch, tmp_path):
    from backend.services import ws_stream_service

    state_path = tmp_path / "bot_state.json"
    heartbeat_path = tmp_path / "heartbeat.json"

    state_path.write_text(
        json.dumps(
            {
                "balance": 160000.0,
                "equity": 159250.0,
                "day_start_equity": 160500.0,
                "mode": "paper",
                "open_positions": [
                    {
                        "ticket": 12345,
                        "symbol": "XAUUSD",
                        "side": "buy",
                        "volume": 0.1,
                        "profit": 125.5,
                    }
                ],
                "last_signal_time": "2026-05-18T10:00:00+00:00",
                "last_signal": {
                    "symbol": "XAUUSD",
                    "timeframe": "M15",
                    "side": "buy",
                    "reason": "breakout",
                    "confidence": 0.82,
                    "time": "2026-05-18T10:00:00+00:00",
                },
                "last_sentiment": {"label": "bullish", "score": 0.4},
                "updated_at": "2026-05-18T10:00:05+00:00",
            }
        ),
        encoding="utf-8",
    )
    heartbeat_path.write_text(
        json.dumps(
            {
                "status": "running",
                "trading_bot_running": True,
                "ts": "2026-05-18T10:00:10+00:00",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(ws_stream_service, "_BOT_STATE", state_path)
    monkeypatch.setattr(ws_stream_service, "_HEARTBEAT", heartbeat_path)

    with api_client.websocket_connect(f"/ws/live?token={issued_token}") as websocket:
        by_type = _receive_until_types(
            websocket,
            {"connection.accepted", "equity.update", "positions.update", "signal.detected", "heartbeat"},
        )

    assert by_type["connection.accepted"]["payload"]["user"] == "admin"
    assert by_type["equity.update"]["payload"]["equity"] == 159250.0
    assert by_type["positions.update"]["payload"]["count"] == 1
    assert by_type["signal.detected"]["payload"]["reason"] == "breakout"
    assert by_type["heartbeat"]["payload"]["trading_bot_running"] is True
