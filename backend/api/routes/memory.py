"""AI memory endpoints — patterns, training data, optimization history."""
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
_REPORTS_DIR = Path("reports")


def _get_memory() -> MemoryLayer:
    return MemoryLayer(load_settings().database_url)


def _read_json(path: Path) -> dict | list:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


@router.get("/patterns", response_model=APIResponse[dict], summary="Winning and losing patterns")
async def patterns(_user: dict = Depends(get_current_user)):
    winning = _read_json(_MEMORY_DIR / "winning_patterns.json")
    losing = _read_json(_MEMORY_DIR / "losing_patterns.json")
    best_params = _read_json(_MEMORY_DIR / "best_parameters.json")

    return APIResponse(data={
        "winning_patterns": winning,
        "losing_patterns": losing,
        "best_parameters": best_params,
        "last_updated": datetime.now(timezone.utc).isoformat(),
    })


@router.get("/training-data", response_model=APIResponse[dict], summary="ML training dataset summary")
async def training_data(_user: dict = Depends(get_current_user)):
    try:
        memory = _get_memory()
        df = memory.trade_history(limit=10000)

        if df.empty:
            return APIResponse(data={"records": 0, "features": [], "samples": []})

        feature_cols = [c for c in df.columns if c not in ("id", "broker_ticket", "notes", "meta")]
        sample_count = len(df)
        wins = len(df[df["pnl"] > 0]) if "pnl" in df.columns else 0
        losses = sample_count - wins

        return APIResponse(data={
            "records": sample_count,
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / sample_count * 100, 1) if sample_count else 0,
            "features": feature_cols,
            "latest_entries": df.tail(10).to_dict(orient="records") if not df.empty else [],
        })
    except Exception as exc:
        logger.exception("Training data fetch failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/model-history", response_model=APIResponse[dict], summary="ML model snapshot history")
async def model_history(_user: dict = Depends(get_current_user)):
    try:
        memory = _get_memory()
        df = memory.model_history()

        if df.empty:
            return APIResponse(data={"snapshots": [], "total": 0})

        records = df.to_dict(orient="records")
        for r in records:
            for k, v in r.items():
                if hasattr(v, "isoformat"):
                    r[k] = v.isoformat()

        return APIResponse(data={"snapshots": records, "total": len(records)})
    except Exception as exc:
        logger.exception("Model history fetch failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/strategy-evolution", response_model=APIResponse[dict], summary="Strategy version evolution log")
async def strategy_evolution(_user: dict = Depends(get_current_user)):
    notes_path = _MEMORY_DIR / "optimization_notes.md"
    notes = notes_path.read_text(encoding="utf-8") if notes_path.exists() else ""

    versions = []
    import glob as _glob
    for v_file in sorted(_glob.glob("strategy_v*.py")):
        stat = Path(v_file).stat()
        versions.append({
            "file": v_file,
            "version": v_file.replace("strategy_", "").replace(".py", ""),
            "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "size_bytes": stat.st_size,
        })

    return APIResponse(data={
        "versions": versions,
        "total": len(versions),
        "latest": versions[-1]["version"] if versions else "unknown",
        "notes": notes,
    })


@router.get("/runtime-state", response_model=APIResponse[dict], summary="Runtime key-value state")
async def runtime_state(_user: dict = Depends(get_current_user)):
    try:
        memory = _get_memory()
        keys = ["last_sentiment", "last_signal", "last_backtest", "optimizer_state", "ai_confidence"]
        result = {}
        for k in keys:
            val = memory.get_runtime_state(k)
            result[k] = val if isinstance(val, dict) else {}

        return APIResponse(data=result)
    except Exception as exc:
        logger.exception("Runtime state fetch failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
