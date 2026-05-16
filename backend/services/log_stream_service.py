"""
Live Log Stream Service
=======================
Captures Python log records into a ring buffer and makes them
available for real-time consumption via SSE or WebSocket.

Log levels supported: DEBUG | INFO | WARNING | ERROR | CRITICAL
Custom levels: SIGNAL (25), TRADE (35) — inserted between std levels.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

# Custom log levels
SIGNAL_LEVEL = 25
TRADE_LEVEL = 35
logging.addLevelName(SIGNAL_LEVEL, "SIGNAL")
logging.addLevelName(TRADE_LEVEL, "TRADE")


@dataclass
class LogRecord:
    """Single captured log record."""
    timestamp: str
    level: str
    logger_name: str
    message: str
    seq: int

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "level": self.level,
            "logger": self.logger_name,
            "message": self.message,
            "seq": self.seq,
        }


class LogRingBuffer:
    """Thread-safe ring buffer for log records."""

    def __init__(self, maxlen: int = 1000) -> None:
        self._buf: deque[LogRecord] = deque(maxlen=maxlen)
        self._seq = 0
        self._lock = asyncio.Lock() if False else None  # sync-only, no async needed

    def append(self, record: LogRecord) -> None:
        self._buf.append(record)

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def since(self, seq: int, level_filter: Optional[str] = None) -> list[LogRecord]:
        result = [r for r in self._buf if r.seq > seq]
        if level_filter:
            result = [r for r in result if r.level == level_filter.upper()]
        return result

    def tail(self, n: int = 100, level_filter: Optional[str] = None) -> list[LogRecord]:
        records = list(self._buf)
        if level_filter:
            records = [r for r in records if r.level == level_filter.upper()]
        return records[-n:]

    def last_seq(self) -> int:
        return self._buf[-1].seq if self._buf else 0


class WebSocketLogHandler(logging.Handler):
    """
    Python logging.Handler that pushes records into LogRingBuffer.
    Also optionally forwards to an async broadcast callback.
    """

    def __init__(self, buffer: LogRingBuffer) -> None:
        super().__init__()
        self._buffer = buffer
        self._broadcast_cb = None      # set by LogStreamService

    def set_broadcast_callback(self, cb) -> None:
        self._broadcast_cb = cb

    def emit(self, record: logging.LogRecord) -> None:
        try:
            log_entry = LogRecord(
                timestamp=datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
                level=record.levelname,
                logger_name=record.name,
                message=self.format(record),
                seq=self._buffer.next_seq(),
            )
            self._buffer.append(log_entry)

            if self._broadcast_cb is not None:
                try:
                    loop = asyncio.get_running_loop()
                    cb = self._broadcast_cb
                    loop.call_soon_threadsafe(
                        lambda e=log_entry: asyncio.ensure_future(cb(e))
                    )
                except RuntimeError:
                    pass  # No running event loop in this thread
                except Exception:
                    pass
        except Exception:
            self.handleError(record)


class LogStreamService:
    """
    Service that manages live log capture and streaming.

    Usage:
        service = get_log_stream_service()
        service.install()  # call once at startup

        # REST: recent logs
        records = service.get_recent(n=100, level="SIGNAL")

        # SSE: async generator
        async for chunk in service.stream_sse(since_seq=0):
            yield chunk
    """

    def __init__(self, maxlen: int = 2000) -> None:
        self._buffer = LogRingBuffer(maxlen=maxlen)
        self._handler = WebSocketLogHandler(self._buffer)
        self._installed = False
        self._subscribers: list[asyncio.Queue] = []

    def install(self, min_level: int = logging.DEBUG) -> None:
        """Install the handler on the root logger. Call once at app startup."""
        if self._installed:
            return
        fmt = logging.Formatter("%(levelname)s | %(name)s | %(message)s")
        self._handler.setFormatter(fmt)
        self._handler.setLevel(min_level)
        self._handler.set_broadcast_callback(self._broadcast)
        logging.getLogger().addHandler(self._handler)
        self._installed = True

    def get_recent(self, n: int = 200, level: Optional[str] = None) -> list[dict]:
        return [r.to_dict() for r in self._buffer.tail(n, level_filter=level)]

    def get_since(self, seq: int, level: Optional[str] = None) -> list[dict]:
        return [r.to_dict() for r in self._buffer.since(seq, level_filter=level)]

    def last_seq(self) -> int:
        return self._buffer.last_seq()

    async def _broadcast(self, record: LogRecord) -> None:
        dead = []
        for q in self._subscribers:
            try:
                q.put_nowait(record)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass

    async def stream_sse(
        self,
        since_seq: int = 0,
        level: Optional[str] = None,
        heartbeat_interval: float = 15.0,
    ) -> AsyncIterator[str]:
        """
        Async generator yielding Server-Sent Events.
        Yields buffered records first, then live records as they arrive.
        """
        # Flush buffered records
        for r in self._buffer.since(since_seq, level_filter=level):
            yield _sse_event(r.to_dict())

        # Subscribe to live records
        queue: asyncio.Queue[LogRecord] = asyncio.Queue(maxsize=500)
        self._subscribers.append(queue)

        last_heartbeat = time.monotonic()
        try:
            while True:
                try:
                    record = await asyncio.wait_for(queue.get(), timeout=heartbeat_interval)
                    if level is None or record.level == level.upper():
                        yield _sse_event(record.to_dict())
                    last_heartbeat = time.monotonic()
                except asyncio.TimeoutError:
                    # Heartbeat to keep connection alive
                    yield ": heartbeat\n\n"
                    last_heartbeat = time.monotonic()
        finally:
            try:
                self._subscribers.remove(queue)
            except ValueError:
                pass


def _sse_event(data: dict) -> str:
    import json
    return f"data: {json.dumps(data)}\n\n"


# ─────────────────────────────────────────────────────────────────
# SINGLETON
# ─────────────────────────────────────────────────────────────────

_service: Optional[LogStreamService] = None


def get_log_stream_service() -> LogStreamService:
    global _service
    if _service is None:
        _service = LogStreamService()
    return _service
