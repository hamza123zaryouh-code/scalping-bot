"""
WebSocket Connection Manager — Realtime event streaming engine.

Supports:
  - Authenticated connections (JWT token)
  - Named event channels (equity, trades, sentiment, regime, risk, ml, logs, heartbeat)
  - Channel subscriptions per connection
  - Broadcast to all or specific channels
  - Automatic dead-connection cleanup
  - Connection health ping/pong
  - Async event queue for non-blocking broadcasts from sync code

Event payload structure:
  {
    "type": "event_type",
    "channel": "equity|trades|sentiment|...",
    "payload": { ... },
    "ts": "ISO8601"
  }
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)
_UTC = timezone.utc

# All valid streaming channels
CHANNELS = frozenset({
    "equity",
    "trades",
    "positions",
    "sentiment",
    "risk",
    "regime",
    "patterns",
    "ml",
    "logs",
    "heartbeat",
    "news",
    "execution",
})


@dataclass
class LiveConnection:
    websocket: WebSocket
    user_id: str
    role: str
    subscriptions: set[str] = field(default_factory=lambda: set(CHANNELS))  # default: all channels
    connected_at: str = field(default_factory=lambda: datetime.now(_UTC).isoformat())
    ping_count: int = 0

    def is_subscribed(self, channel: str) -> bool:
        return "*" in self.subscriptions or channel in self.subscriptions


class ConnectionManager:
    """
    Thread-safe WebSocket connection manager with channel-based subscriptions.

    Designed for use with FastAPI WebSocket endpoints. Broadcasts are async
    and automatically prune dead connections.
    """

    def __init__(self) -> None:
        self._active: list[LiveConnection] = []
        self._lock = asyncio.Lock()
        self._event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=500)
        self._broadcaster_task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def connect(self, ws: WebSocket, *, user_id: str, role: str) -> LiveConnection:
        await ws.accept()
        conn = LiveConnection(websocket=ws, user_id=user_id, role=role)
        async with self._lock:
            self._active.append(conn)
        logger.info(
            "WS connected: user=%s role=%s (total=%d)",
            user_id, role, len(self._active),
        )
        return conn

    def disconnect(self, ws: WebSocket) -> None:
        self._active = [c for c in self._active if c.websocket is not ws]
        logger.info("WS disconnected (total=%d)", len(self._active))

    def update_subscriptions(self, ws: WebSocket, channels: list[str]) -> None:
        valid = set(channels) & CHANNELS
        for conn in self._active:
            if conn.websocket is ws:
                conn.subscriptions = valid if valid else set(CHANNELS)
                return

    async def send_json(self, ws: WebSocket, data: Any) -> None:
        try:
            await ws.send_json(data)
        except Exception as exc:
            logger.debug("WS send failed: %s", exc)
            self.disconnect(ws)

    async def broadcast_event(self, event_type: str, payload: dict[str, Any], channel: str = "*") -> None:
        """Broadcast to all connections subscribed to channel."""
        message = {
            "type": event_type,
            "channel": channel,
            "payload": payload,
            "ts": datetime.now(_UTC).isoformat(),
        }
        await self.broadcast_json(message, channel=channel)

    async def broadcast_json(self, data: Any, channel: str = "*") -> None:
        dead: list[WebSocket] = []
        for conn in list(self._active):
            if not conn.is_subscribed(channel) and channel != "*":
                continue
            try:
                await conn.websocket.send_json(data)
            except Exception:
                dead.append(conn.websocket)
        for ws in dead:
            self.disconnect(ws)

    def enqueue_event(self, event_type: str, payload: dict[str, Any], channel: str = "*") -> None:
        """
        Thread-safe: enqueue an event from synchronous code (e.g. trading loop).
        The async broadcaster will pick it up and broadcast it.
        """
        msg = {
            "type": event_type,
            "channel": channel,
            "payload": payload,
            "ts": datetime.now(_UTC).isoformat(),
        }
        try:
            self._event_queue.put_nowait(msg)
        except asyncio.QueueFull:
            # Drop oldest event if queue is saturated
            try:
                self._event_queue.get_nowait()
                self._event_queue.put_nowait(msg)
            except Exception:
                pass

    async def start_broadcaster(self) -> None:
        """Start the async event broadcaster. Call once from app lifespan."""
        current_loop = asyncio.get_running_loop()
        if self._loop is not current_loop:
            self._loop = current_loop
            self._lock = asyncio.Lock()
            self._event_queue = asyncio.Queue(maxsize=500)
            self._active = []

        if self._broadcaster_task is not None and not self._broadcaster_task.done():
            return
        self._broadcaster_task = asyncio.create_task(self._broadcast_loop())
        logger.info("WebSocket event broadcaster started")

    async def stop_broadcaster(self) -> None:
        if self._broadcaster_task is not None:
            self._broadcaster_task.cancel()
            try:
                await self._broadcaster_task
            except asyncio.CancelledError:
                pass
            finally:
                self._broadcaster_task = None

        while not self._event_queue.empty():
            try:
                self._event_queue.get_nowait()
            except Exception:
                break

    async def _broadcast_loop(self) -> None:
        while True:
            try:
                msg = await asyncio.wait_for(self._event_queue.get(), timeout=1.0)
                await self.broadcast_json(msg, channel=msg.get("channel", "*"))
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception:
                # Avoid logging here: the log stream itself is broadcast through this
                # manager, so warning logs can recursively enqueue new events.
                continue

    # ─────────────────────────────────────────────────────────────
    # Streaming helpers
    # ─────────────────────────────────────────────────────────────

    async def push_equity_update(self, equity: float, balance: float, drawdown_pct: float) -> None:
        await self.broadcast_event("equity.update", {
            "equity": round(equity, 2),
            "balance": round(balance, 2),
            "drawdown_pct": round(drawdown_pct, 3),
        }, channel="equity")

    async def push_trade_opened(self, trade: dict[str, Any]) -> None:
        await self.broadcast_event("trade.opened", trade, channel="trades")

    async def push_trade_closed(self, trade: dict[str, Any]) -> None:
        await self.broadcast_event("trade.closed", trade, channel="trades")

    async def push_signal(self, signal: dict[str, Any]) -> None:
        await self.broadcast_event("signal.detected", signal, channel="trades")

    async def push_sentiment(self, sentiment: dict[str, Any]) -> None:
        await self.broadcast_event("sentiment.update", sentiment, channel="sentiment")

    async def push_risk(self, risk: dict[str, Any]) -> None:
        await self.broadcast_event("risk.update", risk, channel="risk")

    async def push_regime(self, regime: dict[str, Any]) -> None:
        await self.broadcast_event("regime.change", regime, channel="regime")

    async def push_news(self, news: dict[str, Any]) -> None:
        await self.broadcast_event("news.update", news, channel="news")

    async def push_heartbeat(self, health: dict[str, Any]) -> None:
        await self.broadcast_event("heartbeat", health, channel="heartbeat")

    async def push_ml_update(self, ml: dict[str, Any]) -> None:
        await self.broadcast_event("ml.update", ml, channel="ml")

    async def push_execution(self, execution: dict[str, Any]) -> None:
        await self.broadcast_event("execution.update", execution, channel="execution")

    @property
    def connected_count(self) -> int:
        return len(self._active)

    def get_connection_info(self) -> list[dict[str, Any]]:
        return [
            {
                "user_id": c.user_id,
                "role": c.role,
                "subscriptions": sorted(c.subscriptions),
                "connected_at": c.connected_at,
            }
            for c in self._active
        ]


ws_manager = ConnectionManager()
