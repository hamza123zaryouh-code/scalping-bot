"""Shared pytest fixtures for all test suites."""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def configured_test_environment(monkeypatch, tmp_path):
    from backend.core.config import get_settings
    from backend.core.security import hash_password

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("SECRET_KEY", "test_secret_key_32_characters_long")
    monkeypatch.setenv("AUTH_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("AUTH_ADMIN_PASSWORD_HASH", hash_password("correct-password"))
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
    monkeypatch.setenv("BOT_MODE", "paper")
    monkeypatch.setenv("POSTGRES_URL", f"sqlite:///{(tmp_path / 'autonomous-test.db').as_posix()}")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def sample_ohlcv() -> pd.DataFrame:
    """60 bars of synthetic OHLCV - reproducible with fixed seed."""
    rng = np.random.default_rng(42)
    n = 60
    close = 1900.0 + np.cumsum(rng.normal(0, 5, n))
    open_ = close + rng.normal(0, 2, n)
    high = np.maximum(close, open_) + np.abs(rng.normal(0, 3, n))
    low = np.minimum(close, open_) - np.abs(rng.normal(0, 3, n))
    vol = rng.integers(800, 3000, n).astype(float)

    idx = pd.date_range("2026-01-01 09:00", periods=n, freq="1min")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": vol}, index=idx)


@pytest.fixture
def ftmo_limits():
    from risk_manager import build_ftmo_limits

    return build_ftmo_limits(start_capital=160000.0, max_daily_loss=8000.0, max_total_loss=16000.0)


@pytest.fixture
def api_client():
    from backend.api.deps import get_current_user
    from backend.main import create_app

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: {"sub": "test_user", "role": "admin"}

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
def strict_api_client():
    from backend.main import create_app

    app = create_app()
    with TestClient(app) as client:
        yield client


@pytest.fixture
def issued_token(strict_api_client):
    response = strict_api_client.post(
        "/api/v1/auth/token",
        data={"username": "admin", "password": "correct-password"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


@pytest.fixture
def expired_token():
    from backend.core.security import create_access_token

    return create_access_token({"sub": "admin", "role": "admin"}, expires_delta=timedelta(minutes=-5))
