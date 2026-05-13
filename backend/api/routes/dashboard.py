"""Live dashboard endpoints."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from backend.api.deps import get_current_user
from backend.api.schemas.common import APIResponse

logger = logging.getLogger(__name__)
router = APIRouter()

_STATE_PATH = Path("live_logs/bot_state.json")


def _load_bot_state() -> dict:
    if not _STATE_PATH.exists():
        return {}
    try:
        return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


@router.get("/live", response_model=APIResponse[dict], summary="Live dashboard snapshot")
async def live_dashboard(_user: dict = Depends(get_current_user)):
    state = _load_bot_state()
    return APIResponse(
        data={
            "timestamp": datetime.utcnow().isoformat(),
            "bot_state": state,
            "status": "live" if state else "no_data",
        }
    )


@router.get("/equity", summary="Equity curve for today")
async def equity_curve(_user: dict = Depends(get_current_user)):
    log_path = Path("live_logs/xauusd_live_bot.log")
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="No live log found")

    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    equity_points = [
        line for line in lines
        if "equity=" in line or "balance=" in line
    ][-200:]

    return APIResponse(data={"log_lines": equity_points})
