"""Smoke tests — verify the full pipeline can initialise without crashing."""
from __future__ import annotations

from pathlib import Path

import pytest


def test_risk_manager_imports():
    from core.risk_manager import build_ftmo_limits
    limits = build_ftmo_limits(160000, 8000, 16000)
    assert limits.min_allowed_equity == pytest.approx(144000)


def test_backend_app_creates():
    from backend.main import create_app
    app = create_app()
    assert app is not None
    assert app.title == "XAUUSD Trading Platform API"


def test_api_health(api_client):
    r = api_client.get("/api/v1/health")
    assert r.status_code == 200


def test_risk_service_instantiates():
    from backend.services.risk_service import RiskService
    svc = RiskService()
    snapshot = svc.get_snapshot()
    assert snapshot.equity > 0
    assert snapshot.ftmo_status.risk_level in {"green", "yellow", "red"}


def test_exports_dirs_exist():
    for d in ["exports/latest", "exports/history", "exports/reports", "logs"]:
        Path(d).mkdir(parents=True, exist_ok=True)
    assert Path("exports").exists()
