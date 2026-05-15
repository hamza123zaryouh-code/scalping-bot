"""Live log streaming endpoints."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from backend.api.deps import get_current_user
from backend.api.schemas.common import APIResponse
from backend.services.log_stream_service import get_log_stream_service

logger = logging.getLogger(__name__)
router = APIRouter()

_VALID_LEVELS = {"DEBUG", "INFO", "SIGNAL", "WARNING", "TRADE", "ERROR", "CRITICAL"}


def _validate_level(level: Optional[str]) -> Optional[str]:
    if level is None:
        return None
    upper = level.upper()
    return upper if upper in _VALID_LEVELS else None


@router.get("/recent", response_model=APIResponse[dict], summary="Recent log entries")
async def recent_logs(
    n: int = Query(default=200, ge=1, le=2000),
    level: Optional[str] = Query(default=None, description="Filter: DEBUG|INFO|SIGNAL|WARNING|TRADE|ERROR|CRITICAL"),
    _user: dict = Depends(get_current_user),
):
    """Return the last N log entries from the ring buffer."""
    svc = get_log_stream_service()
    records = svc.get_recent(n=n, level=_validate_level(level))
    return APIResponse(data={
        "records": records,
        "total": len(records),
        "last_seq": svc.last_seq(),
    })


@router.get("/since/{seq}", response_model=APIResponse[dict], summary="Log entries since sequence number")
async def logs_since(
    seq: int,
    level: Optional[str] = Query(default=None),
    _user: dict = Depends(get_current_user),
):
    """Return log entries newer than the given sequence number (for polling)."""
    svc = get_log_stream_service()
    records = svc.get_since(seq=seq, level=_validate_level(level))
    return APIResponse(data={
        "records": records,
        "total": len(records),
        "last_seq": svc.last_seq(),
    })


@router.get("/stream", summary="SSE live log stream (Server-Sent Events)")
async def stream_logs(
    since: int = Query(default=0, description="Start from this sequence number"),
    level: Optional[str] = Query(default=None),
    _user: dict = Depends(get_current_user),
):
    """
    Stream log entries as Server-Sent Events.

    Connect with EventSource in the browser or curl --no-buffer.
    Each event is a JSON object: {timestamp, level, logger, message, seq}.
    A heartbeat comment (': heartbeat') is sent every 15 seconds to keep the connection alive.

    Example:
        const es = new EventSource('/api/v1/logs/stream?token=...&level=SIGNAL');
        es.onmessage = (e) => console.log(JSON.parse(e.data));
    """
    svc = get_log_stream_service()
    return StreamingResponse(
        svc.stream_sse(since_seq=since, level=_validate_level(level)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
