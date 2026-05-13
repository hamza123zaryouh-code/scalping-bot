"""WebSocket connection manager for authenticated live events."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


@dataclass
class LiveConnection:
    websocket: WebSocket
    user_id: str
    role: str


class ConnectionManager:
    def __init__(self) -> None:
        self._active: list[LiveConnection] = []

    async def connect(self, ws: WebSocket, *, user_id: str, role: str) -> None:
        await ws.accept()
        self._active.append(LiveConnection(websocket=ws, user_id=user_id, role=role))
        logger.info("WebSocket client connected for user '%s' (total=%d)", user_id, len(self._active))

    def disconnect(self, ws: WebSocket) -> None:
        self._active = [connection for connection in self._active if connection.websocket is not ws]
        logger.info("WebSocket client disconnected (total=%d)", len(self._active))

    async def send_json(self, ws: WebSocket, data: Any) -> None:
        await ws.send_json(data)

    async def broadcast_event(self, event_type: str, payload: dict[str, Any]) -> None:
        await self.broadcast_json({"type": event_type, "payload": payload})

    async def broadcast_json(self, data: Any) -> None:
        dead: list[WebSocket] = []
        for connection in list(self._active):
            try:
                await connection.websocket.send_json(data)
            except Exception:
                dead.append(connection.websocket)
        for ws in dead:
            self.disconnect(ws)

    @property
    def connected_count(self) -> int:
        return len(self._active)


ws_manager = ConnectionManager()
