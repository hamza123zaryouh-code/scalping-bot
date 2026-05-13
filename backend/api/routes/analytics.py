"""Trade analytics endpoints backed by the autonomous engine database."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import OperationalError, SQLAlchemyError

from autonomous_xauusd.analytics_engine import compute_report
from autonomous_xauusd.memory_layer import MemoryLayer
from autonomous_xauusd.settings import load_settings
from backend.api.deps import get_current_user
from backend.api.schemas.common import APIResponse

logger = logging.getLogger(__name__)
router = APIRouter()


def get_memory() -> MemoryLayer:
    settings = load_settings()
    return MemoryLayer(settings.database_url)


def _raise_analytics_error(exc: Exception) -> None:
    if isinstance(exc, OperationalError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Analytics database is unavailable.",
        ) from exc
    if isinstance(exc, SQLAlchemyError):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Analytics query failed.",
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Analytics request failed.",
    ) from exc


def _ensure_mapping(value: Any, *, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Analytics state '{field_name}' is malformed.",
        )
    return value


@router.get("/metrics", summary="Aggregate performance metrics")
async def metrics(
    _user: dict = Depends(get_current_user),
    memory: MemoryLayer = Depends(get_memory),
):
    try:
        history = memory.trade_history(limit=5000)
        ml_hist = memory.model_history()
        report = compute_report(history, ml_hist)
        return APIResponse(data=report.to_dict(), message="OK")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Analytics metrics failed")
        _raise_analytics_error(exc)


@router.get("/monthly", summary="Month-by-month summary")
async def monthly(
    _user: dict = Depends(get_current_user),
    memory: MemoryLayer = Depends(get_memory),
):
    try:
        history = memory.trade_history(limit=5000)
        report = compute_report(history)
        return APIResponse(data=report.monthly, message="OK")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Analytics monthly failed")
        _raise_analytics_error(exc)


@router.get("/session", summary="Session-hour performance breakdown")
async def session_analytics(
    _user: dict = Depends(get_current_user),
    memory: MemoryLayer = Depends(get_memory),
):
    try:
        history = memory.trade_history(limit=5000)
        report = compute_report(history)
        return APIResponse(data=report.by_session, message="OK")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Analytics session failed")
        _raise_analytics_error(exc)


@router.get("/regime", summary="Performance per market regime")
async def regime_analytics(
    _user: dict = Depends(get_current_user),
    memory: MemoryLayer = Depends(get_memory),
):
    try:
        history = memory.trade_history(limit=5000)
        report = compute_report(history)
        return APIResponse(data=report.by_regime, message="OK")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Analytics regime failed")
        _raise_analytics_error(exc)


@router.get("/sentiment", summary="Latest sentiment status")
async def sentiment_status(
    _user: dict = Depends(get_current_user),
    memory: MemoryLayer = Depends(get_memory),
):
    try:
        state = _ensure_mapping(memory.get_runtime_state("last_sentiment"), field_name="last_sentiment")
        return APIResponse(data=state, message="OK")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Sentiment status failed")
        _raise_analytics_error(exc)


@router.get("/ml", summary="ML model history")
async def ml_history(
    _user: dict = Depends(get_current_user),
    memory: MemoryLayer = Depends(get_memory),
):
    try:
        ml_hist = memory.model_history()
        records = ml_hist.to_dict(orient="records") if not ml_hist.empty else []
        return APIResponse(data=records, message="OK")
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("ML history failed")
        _raise_analytics_error(exc)
