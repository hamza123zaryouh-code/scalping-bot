"""Telegram control endpoints used by the inline keyboard bot."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from backend.api.deps import require_telegram_api_key
from backend.api.schemas.common import APIResponse
from backend.api.schemas.telegram import (
    TelegramActionRequest,
    TelegramActionResponse,
    TelegramToggleRequest,
)
from backend.services.telegram_service import TelegramService

logger = logging.getLogger(__name__)
router = APIRouter()
_service = TelegramService()


@router.get("/status", response_model=APIResponse[dict], summary="Telegram dashboard status")
async def telegram_status(_key: str = Depends(require_telegram_api_key)):
    return APIResponse(data=_service.get_status_overview())


@router.post("/control/{action}", response_model=APIResponse[TelegramActionResponse], summary="Telegram control action")
async def telegram_control(
    action: str,
    payload: TelegramActionRequest,
    _key: str = Depends(require_telegram_api_key),
):
    try:
        result = _service.handle_control_action(
            action=action,
            telegram_user_id=payload.telegram_user_id,
            telegram_username=payload.telegram_username,
            confirmed=payload.confirmed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return APIResponse(data=TelegramActionResponse(**result), message=result["summary"])


@router.get("/risk/{section}", response_model=APIResponse[dict], summary="Telegram risk snapshots")
async def telegram_risk(section: str, _key: str = Depends(require_telegram_api_key)):
    try:
        return APIResponse(data=_service.get_risk_status(section), message="Risk snapshot loaded")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/signals/{section}", response_model=APIResponse[dict], summary="Telegram signal snapshots")
async def telegram_signals(section: str, _key: str = Depends(require_telegram_api_key)):
    try:
        return APIResponse(data=_service.get_signal_snapshot(section), message="Signal snapshot loaded")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/signals/toggle", response_model=APIResponse[dict], summary="Enable or disable signals")
async def telegram_toggle_signals(
    payload: TelegramToggleRequest,
    _key: str = Depends(require_telegram_api_key),
):
    result = _service.toggle_signals(
        enabled=payload.enabled,
        telegram_user_id=payload.telegram_user_id,
        telegram_username=payload.telegram_username,
    )
    return APIResponse(data=result, message=result["summary"])


@router.post("/backtest/quick-run", response_model=APIResponse[dict], summary="Run Telegram quick backtest")
async def telegram_quick_backtest(
    payload: TelegramActionRequest,
    _key: str = Depends(require_telegram_api_key),
):
    result = _service.run_quick_backtest(payload.telegram_user_id, payload.telegram_username)
    return APIResponse(data=result, message=result["summary"])


@router.get("/backtest/latest", response_model=APIResponse[dict], summary="Latest backtest result")
async def telegram_backtest_latest(_key: str = Depends(require_telegram_api_key)):
    result = _service.get_latest_backtest_result()
    return APIResponse(data=result, message=result["summary"])


@router.get("/backtest/compare", response_model=APIResponse[dict], summary="Compare V16 with V17")
async def telegram_backtest_compare(_key: str = Depends(require_telegram_api_key)):
    result = _service.compare_v16_vs_v17()
    return APIResponse(data=result, message=result["summary"])


@router.get("/backtest/equity-curve-summary", response_model=APIResponse[dict], summary="Equity curve summary")
async def telegram_backtest_equity_curve(_key: str = Depends(require_telegram_api_key)):
    result = _service.get_equity_curve_summary()
    return APIResponse(data=result, message=result["summary"])


@router.post("/memory/train", response_model=APIResponse[TelegramActionResponse], summary="Queue AI training")
async def telegram_train_ai(
    payload: TelegramActionRequest,
    _key: str = Depends(require_telegram_api_key),
):
    result = _service.handle_control_action(
        action="train_ai",
        telegram_user_id=payload.telegram_user_id,
        telegram_username=payload.telegram_username,
        confirmed=True,
    )
    return APIResponse(data=TelegramActionResponse(**result), message=result["summary"])


@router.get("/memory/{section}", response_model=APIResponse[dict], summary="Telegram AI memory snapshots")
async def telegram_memory(section: str, _key: str = Depends(require_telegram_api_key)):
    try:
        result = _service.get_memory_snapshot(section)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return APIResponse(data=result, message=result["summary"])


@router.get("/reports/{period}", response_model=APIResponse[dict], summary="Telegram report summary")
async def telegram_report(period: str, _key: str = Depends(require_telegram_api_key)):
    try:
        result = _service.build_report_snapshot(period)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return APIResponse(data=result, message=result["summary"])


@router.post("/reports/export-trade-log", response_model=APIResponse[dict], summary="Export trade log CSV")
async def telegram_export_trade_log(
    payload: TelegramActionRequest,
    _key: str = Depends(require_telegram_api_key),
):
    result = _service.export_trade_log(payload.telegram_user_id, payload.telegram_username)
    return APIResponse(data=result, message=result["summary"])


@router.get("/audit", response_model=APIResponse[dict], summary="Recent Telegram audit trail")
async def telegram_audit(_key: str = Depends(require_telegram_api_key)):
    return APIResponse(data=_service.recent_action_logs(), message="Recent Telegram audit trail loaded")
