from __future__ import annotations

import pytest
from starlette.websockets import WebSocketDisconnect


def test_websocket_rejects_missing_token(strict_api_client):
    with pytest.raises(WebSocketDisconnect):
        with strict_api_client.websocket_connect("/ws/live"):
            pass


def test_websocket_accepts_authenticated_client(strict_api_client, issued_token):
    with strict_api_client.websocket_connect(f"/ws/live?token={issued_token}") as websocket:
        message = websocket.receive_json()

    assert message["type"] == "connection.accepted"
    assert message["payload"]["user"] == "admin"


def test_websocket_does_not_broadcast_arbitrary_client_payload(strict_api_client, issued_token):
    with strict_api_client.websocket_connect(f"/ws/live?token={issued_token}") as ws1:
        with strict_api_client.websocket_connect(f"/ws/live?token={issued_token}") as ws2:
            assert ws1.receive_json()["type"] == "connection.accepted"
            assert ws2.receive_json()["type"] == "connection.accepted"

            ws1.send_json({"type": "arbitrary", "payload": {"exploit": True}})
            error_message = ws1.receive_json()
            assert error_message["type"] == "error"
            assert "Unsupported client message type" in error_message["error"]

            ws2.send_json({"type": "ping"})
            pong_message = ws2.receive_json()
            assert pong_message["type"] == "pong"
