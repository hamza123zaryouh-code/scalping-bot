"""Risk management and FTMO compliance endpoints."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from backend.api.deps import get_current_user
from backend.api.schemas.common import APIResponse
from backend.api.schemas.risk import FTMOBufferStatus, RiskSnapshot
from backend.services.risk_service import RiskService

logger = logging.getLogger(__name__)
router = APIRouter()
_service = RiskService()


@router.get("/status", response_model=APIResponse[RiskSnapshot], summary="Current risk snapshot")
async def risk_status(_user: dict = Depends(get_current_user)):
    try:
        snapshot = _service.get_snapshot()
        return APIResponse(data=snapshot)
    except Exception as exc:
        logger.exception("Failed to compute risk snapshot")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/ftmo", response_model=APIResponse[FTMOBufferStatus], summary="FTMO buffer compliance check")
async def ftmo_status(
    equity: float = 160000.0,
    day_start_equity: float = 160000.0,
    estimated_trade_risk: float = 400.0,
    _user: dict = Depends(get_current_user),
):
    result = _service.compute_ftmo_buffers(
        equity=equity,
        day_start_equity=day_start_equity,
        estimated_trade_risk=estimated_trade_risk,
    )
    return APIResponse(data=result)
