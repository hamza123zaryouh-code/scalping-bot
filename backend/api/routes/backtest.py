"""XAUUSD V17 Backtest endpoints — async queue + websocket progress."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status

from backend.api.deps import get_current_user
from backend.api.schemas.backtest import BacktestRequest, BacktestResult
from backend.api.schemas.common import APIResponse, TaskStatus
from backend.services.backtest_service import BacktestService

logger = logging.getLogger(__name__)
router = APIRouter()
_service = BacktestService()


@router.post(
    "/run",
    response_model=APIResponse[BacktestResult],
    summary="Run V17 backtest via strategy_engine (sync)",
)
async def run_backtest(
    payload: BacktestRequest,
    _user: dict = Depends(get_current_user),
):
    """
    Synchrone backtest — wacht op voltooiing.
    Gebruikt dezelfde V16 strategy_engine als de live trading bot.
    """
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: _service.run(payload))
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Data niet beschikbaar: {exc}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Backtest mislukt")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Backtest engine fout: {exc}",
        ) from exc

    return APIResponse(
        data=result,
        message=f"Backtest voltooid: {result.metrics.total_trades} trades, "
                f"WR={result.metrics.win_rate:.0%}, PF={result.metrics.profit_factor:.2f}",
    )


@router.post(
    "/run-async",
    response_model=APIResponse[dict],
    summary="Start async backtest — retourneert task_id",
)
async def run_backtest_async(
    payload: BacktestRequest,
    _user: dict = Depends(get_current_user),
):
    """
    Asynchrone backtest — retourneert task_id direct.
    Poll /status/{task_id} of gebruik /ws/backtest-progress/{task_id}.
    """
    task_id = await _service.run_async(payload)
    return APIResponse(
        data={"task_id": task_id, "status": "started"},
        message="Backtest gestart — poll /status/{task_id} voor voortgang",
    )


@router.get(
    "/status/{task_id}",
    response_model=APIResponse[TaskStatus],
    summary="Backtest voortgang opvragen",
)
async def backtest_status(task_id: str, _user: dict = Depends(get_current_user)):
    task = _service.status(task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Backtest task niet gevonden: {task_id}",
        )
    return APIResponse(data=task)


@router.get(
    "/result/{task_id}",
    response_model=APIResponse[BacktestResult],
    summary="Backtest resultaat ophalen",
)
async def backtest_result(task_id: str, _user: dict = Depends(get_current_user)):
    result = _service.result(task_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Backtest resultaat niet gevonden (nog bezig?): {task_id}",
        )
    return APIResponse(data=result)


@router.get(
    "/latest",
    response_model=APIResponse[BacktestResult],
    summary="Laatste beschikbare backtest resultaat",
)
async def latest_backtest(_user: dict = Depends(get_current_user)):
    result = _service.get_latest_result()
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nog geen backtest resultaat beschikbaar.",
        )
    return APIResponse(data=result)


@router.get(
    "/history",
    response_model=APIResponse[list],
    summary="Backtest geschiedenis",
)
async def backtest_history(_user: dict = Depends(get_current_user)):
    """Lijst van recente backtests (max 50)."""
    history = _service.get_history()
    return APIResponse(
        data=history,
        message=f"{len(history)} backtests in geschiedenis",
    )


@router.websocket("/ws/progress/{task_id}")
async def backtest_progress_ws(websocket: WebSocket, task_id: str):
    """
    WebSocket voor real-time backtest voortgang.
    Stuurt progress updates elke 500ms tot voltooid of gefaald.
    """
    await websocket.accept()
    try:
        while True:
            prog = _service.get_progress(task_id)
            if prog is None:
                await websocket.send_json({"error": "Task niet gevonden", "task_id": task_id})
                break

            await websocket.send_json(prog)

            if prog["status"] in ("completed", "failed"):
                break

            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        logger.debug("WebSocket backtest progress verbroken: %s", task_id)
    except Exception as e:
        logger.error("WebSocket backtest fout: %s", e)
        try:
            await websocket.send_json({"error": str(e)})
        except Exception:
            pass
