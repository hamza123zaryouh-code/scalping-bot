"""Backtest endpoints backed by the local exported XAUUSD dataset."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from backend.api.deps import get_current_user
from backend.api.schemas.backtest import BacktestRequest, BacktestResult
from backend.api.schemas.common import APIResponse, TaskStatus
from backend.services.backtest_service import BacktestService

router = APIRouter()
_service = BacktestService()


@router.post("/run", response_model=APIResponse[BacktestResult], summary="Run a local XAUUSD backtest replay")
async def run_backtest(
    payload: BacktestRequest,
    _user: dict = Depends(get_current_user),
):
    try:
        result = _service.run(payload)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    return APIResponse(
        data=result,
        message="Backtest replay completed using the latest local exported XAUUSD dataset.",
    )


@router.get("/status/{task_id}", response_model=APIResponse[TaskStatus], summary="Get local backtest task status")
async def backtest_status(task_id: str, _user: dict = Depends(get_current_user)):
    task = _service.status(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backtest task not found.")
    return APIResponse(data=task)


@router.get("/result/{task_id}", response_model=APIResponse[BacktestResult], summary="Get local backtest result")
async def backtest_result(task_id: str, _user: dict = Depends(get_current_user)):
    result = _service.result(task_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backtest task not found.")
    return APIResponse(data=result)
