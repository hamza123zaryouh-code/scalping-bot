from __future__ import annotations

import pytest
from starlette.websockets import WebSocketDisconnect


def _receive_until_type(websocket, message_type: str, max_messages: int = 10):
    for _ in range(max_messages):
        message = websocket.receive_json()
        if message.get("type") == message_type:
            return message
    raise AssertionError(f"Did not receive websocket message type {message_type!r}")


def test_websocket_rejects_missing_token(strict_api_client):
    with pytest.raises(WebSocketDisconnect):
        with strict_api_client.websocket_connect("/ws/live"):
            pass


def test_websocket_accepts_authenticated_client(strict_api_client, issued_token):
    with strict_api_client.websocket_connect(f"/ws/live?token={issued_token}") as websocket:
        message = _receive_until_type(websocket, "connection.accepted")

    assert message["type"] == "connection.accepted"
    assert message["payload"]["user"] == "admin"


def test_websocket_does_not_broadcast_arbitrary_client_payload(strict_api_client, issued_token):
    with strict_api_client.websocket_connect(f"/ws/live?token={issued_token}") as ws1:
        with strict_api_client.websocket_connect(f"/ws/live?token={issued_token}") as ws2:
            assert _receive_until_type(ws1, "connection.accepted")["type"] == "connection.accepted"
            assert _receive_until_type(ws2, "connection.accepted")["type"] == "connection.accepted"

            ws1.send_json({"type": "arbitrary", "payload": {"exploit": True}})
            error_message = _receive_until_type(ws1, "error")
            assert error_message["type"] == "error"
            assert "Unsupported client message type" in error_message["error"]

            ws2.send_json({"type": "ping"})
            pong_message = _receive_until_type(ws2, "pong")
            assert pong_message["type"] == "pong"
