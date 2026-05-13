"""Signal and open-position endpoints."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from backend.api.deps import get_current_user
from backend.api.schemas.common import APIResponse
from backend.api.schemas.signals import LiveSignalResponse, OpenPosition
from backend.services.signal_service import SignalService

logger = logging.getLogger(__name__)
router = APIRouter()
_service = SignalService()


@router.get("/live", response_model=APIResponse[LiveSignalResponse | None], summary="Latest live signal")
async def live_signal(_user: dict = Depends(get_current_user)):
    signal = _service.get_latest_signal()
    return APIResponse(data=signal, message="No signal" if signal is None else "Signal found")


@router.get("/positions/open", response_model=APIResponse[list[OpenPosition]], summary="Open MT5 positions")
async def open_positions(_user: dict = Depends(get_current_user)):
    positions = _service.get_open_positions()
    return APIResponse(data=positions)
