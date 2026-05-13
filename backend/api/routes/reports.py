"""Report listing and download endpoints."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from backend.api.deps import get_current_user
from backend.api.schemas.common import APIResponse

logger = logging.getLogger(__name__)
router = APIRouter()

_REPORT_DIRS = [
    Path("exports/reports"),
    Path("exports/latest"),
    Path("exports/history"),
]
_ALLOWED_EXTS = {".pdf", ".png", ".csv"}


def _list_reports() -> list[dict]:
    seen: set[str] = set()
    reports = []
    for d in _REPORT_DIRS:
        if not d.exists():
            continue
        for p in sorted(d.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True):
            if p.is_file() and p.suffix in _ALLOWED_EXTS and p.name not in seen:
                seen.add(p.name)
                reports.append(
                    {
                        "name": p.name,
                        "path": str(p),
                        "size_kb": round(p.stat().st_size / 1024, 1),
                        "modified": p.stat().st_mtime,
                        "type": p.suffix.lstrip("."),
                    }
                )
    return reports


@router.get("/list", summary="List available report artefacts")
async def list_reports(_user: dict = Depends(get_current_user)):
    items = _list_reports()
    return APIResponse(data={"reports": items, "count": len(items)})


@router.get("/download/{filename}", summary="Download a report file")
async def download_report(filename: str, _user: dict = Depends(get_current_user)):
    # Security: prevent path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    for d in _REPORT_DIRS:
        candidate = d / filename
        if candidate.exists() and candidate.is_file() and candidate.suffix in _ALLOWED_EXTS:
            return FileResponse(path=str(candidate), filename=filename)

    raise HTTPException(status_code=404, detail=f"Report '{filename}' not found")
