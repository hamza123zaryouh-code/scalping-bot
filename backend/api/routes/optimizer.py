"""Strategy optimizer endpoints."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from autonomous_xauusd.memory_layer import MemoryLayer
from autonomous_xauusd.settings import load_settings
from backend.api.deps import get_current_user
from backend.api.schemas.common import APIResponse
from backend.services.optimizer_service import OptimizerRequest, get_optimizer_service

logger = logging.getLogger(__name__)
router = APIRouter()

_MEMORY_DIR = Path("memory")
_RESULTS_DIR = Path("results")


def _get_memory() -> MemoryLayer:
    return MemoryLayer(load_settings().database_url)


def _read_json(path: Path) -> dict | list:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ─────────────────────────────────────────────────────────────────
# REQUEST SCHEMAS
# ─────────────────────────────────────────────────────────────────

class RunOptimizerBody(BaseModel):
    start_date: date
    end_date: date
    symbol: str = "XAUUSD"
    starting_capital: float = 160_000.0
    param_grid: dict[str, list[Any]] | None = None
    walk_forward_splits: int = Field(default=3, ge=2, le=10)
    is_pct: float = Field(default=0.70, ge=0.50, le=0.90)
    max_combinations: int = Field(default=50, ge=1, le=500)
    objective: str = Field(default="sharpe", pattern="^(sharpe|profit|win_rate)$")


# ─────────────────────────────────────────────────────────────────
# OPTIMIZER JOB ENDPOINTS
# ─────────────────────────────────────────────────────────────────

@router.post("/run", response_model=APIResponse[dict], summary="Start an async optimizer job")
async def run_optimizer(body: RunOptimizerBody, _user: dict = Depends(get_current_user)):
    """Launch a grid-search + walk-forward optimizer job in the background."""
    request = OptimizerRequest(
        start_date=body.start_date,
        end_date=body.end_date,
        symbol=body.symbol,
        starting_capital=body.starting_capital,
        walk_forward_splits=body.walk_forward_splits,
        is_pct=body.is_pct,
        max_combinations=body.max_combinations,
        objective=body.objective,
    )
    if body.param_grid is not None:
        request.param_grid = body.param_grid

    service = get_optimizer_service()
    job_id = await service.start_job(request)
    return APIResponse(data={"job_id": job_id, "status": "running", "message": "Optimizer job started"})


@router.get("/jobs", response_model=APIResponse[dict], summary="List all optimizer jobs")
async def list_jobs(_user: dict = Depends(get_current_user)):
    service = get_optimizer_service()
    jobs = service.list_jobs()
    return APIResponse(data={"jobs": jobs, "total": len(jobs)})


@router.get("/jobs/{job_id}/status", response_model=APIResponse[dict], summary="Get optimizer job status")
async def job_status(job_id: str, _user: dict = Depends(get_current_user)):
    service = get_optimizer_service()
    job = service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return APIResponse(data=job)


@router.get("/best-parameters", response_model=APIResponse[dict], summary="Best performing parameters")
async def best_parameters(_user: dict = Depends(get_current_user)):
    service = get_optimizer_service()
    best = service.get_best_params()
    if best is None:
        # Fallback to legacy file
        best = _read_json(_MEMORY_DIR / "best_parameters.json")
    return APIResponse(data={"parameters": best, "timestamp": datetime.now(timezone.utc).isoformat()})


@router.get("/history", response_model=APIResponse[dict], summary="Optimization run history")
async def optimization_history(_user: dict = Depends(get_current_user)):
    service = get_optimizer_service()
    history = service.get_history()
    return APIResponse(data={"runs": history, "total": len(history)})


@router.get("/performance-ranking", response_model=APIResponse[dict], summary="Parameter performance ranking")
async def performance_ranking(_user: dict = Depends(get_current_user)):
    try:
        memory = _get_memory()
        df = memory.trade_history(limit=5000)

        if df.empty:
            return APIResponse(data={"ranking": []})

        ranking = []

        if "signal_type" in df.columns and "pnl" in df.columns:
            by_signal = df.groupby("signal_type")["pnl"].agg(
                total_pnl="sum",
                count="count",
                wins=lambda x: (x > 0).sum(),
            ).reset_index()

            for _, row in by_signal.iterrows():
                total = int(row["count"])
                wins = int(row["wins"])
                ranking.append({
                    "signal_type": row["signal_type"],
                    "total_pnl": round(float(row["total_pnl"]), 2),
                    "count": total,
                    "wins": wins,
                    "win_rate": round(wins / total * 100, 1) if total > 0 else 0,
                })

            ranking.sort(key=lambda x: x["total_pnl"], reverse=True)

        return APIResponse(data={"ranking": ranking})
    except Exception as exc:
        logger.exception("Performance ranking failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/session-analysis", response_model=APIResponse[dict], summary="Performance by trading session")
async def session_analysis(_user: dict = Depends(get_current_user)):
    try:
        memory = _get_memory()
        df = memory.trade_history(limit=5000)

        if df.empty:
            return APIResponse(data={"sessions": []})

        sessions = []
        if "opened_at" in df.columns and "pnl" in df.columns:
            import pandas as pd
            df["hour"] = pd.to_datetime(df["opened_at"]).dt.hour

            def _session(h: int) -> str:
                if 0 <= h < 7:
                    return "Asian"
                if 7 <= h < 12:
                    return "London Open"
                if 12 <= h < 16:
                    return "NY Open"
                if 16 <= h < 20:
                    return "NY Afternoon"
                return "After Hours"

            df["session"] = df["hour"].apply(_session)
            by_session = df.groupby("session")["pnl"].agg(
                total_pnl="sum",
                count="count",
                wins=lambda x: (x > 0).sum(),
            ).reset_index()

            for _, row in by_session.iterrows():
                total = int(row["count"])
                wins = int(row["wins"])
                sessions.append({
                    "session": row["session"],
                    "total_pnl": round(float(row["total_pnl"]), 2),
                    "count": total,
                    "win_rate": round(wins / total * 100, 1) if total > 0 else 0,
                })

        return APIResponse(data={"sessions": sessions})
    except Exception as exc:
        logger.exception("Session analysis failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
