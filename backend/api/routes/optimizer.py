"""Strategy optimizer endpoints."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from autonomous_xauusd.memory_layer import MemoryLayer
from autonomous_xauusd.settings import load_settings
from backend.api.deps import get_current_user
from backend.api.schemas.common import APIResponse

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


@router.get("/best-parameters", response_model=APIResponse[dict], summary="Best performing parameters")
async def best_parameters(_user: dict = Depends(get_current_user)):
    params = _read_json(_MEMORY_DIR / "best_parameters.json")
    return APIResponse(data={"parameters": params, "timestamp": datetime.now(timezone.utc).isoformat()})


@router.get("/history", response_model=APIResponse[dict], summary="Optimization run history")
async def optimization_history(_user: dict = Depends(get_current_user)):
    history = []
    if _RESULTS_DIR.exists():
        for f in sorted(_RESULTS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:50]:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                data["filename"] = f.name
                data["created"] = datetime.fromtimestamp(
                    f.stat().st_mtime, tz=timezone.utc
                ).isoformat()
                history.append(data)
            except Exception:
                continue

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
