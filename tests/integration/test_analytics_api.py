from __future__ import annotations

import pandas as pd
from sqlalchemy.exc import OperationalError


class FakeMemory:
    def __init__(self, *, history=None, ml_history=None, state=None, error=None):
        self._history = history if history is not None else pd.DataFrame()
        self._ml_history = ml_history if ml_history is not None else pd.DataFrame()
        self._state = state
        self._error = error

    def trade_history(self, limit=5000):  # noqa: ARG002
        if self._error:
            raise self._error
        return self._history

    def model_history(self):
        if self._error:
            raise self._error
        return self._ml_history

    def get_runtime_state(self, key):  # noqa: ARG002
        if self._error:
            raise self._error
        return self._state


def _override_memory(app, memory):
    from backend.api.routes.analytics import get_memory

    app.dependency_overrides[get_memory] = lambda: memory


def test_metrics_returns_report(api_client):
    from backend.main import create_app

    history = pd.DataFrame(
        [
            {
                "status": "closed",
                "opened_at": "2026-01-01T09:00:00Z",
                "pnl": 120.0,
                "reward_risk_ratio": 2.0,
                "market_regime": "trend",
                "side": "buy",
            }
        ]
    )
    ml_history = pd.DataFrame(
        [
            {
                "trained_at": "2026-01-02T00:00:00Z",
                "accuracy": 0.62,
                "precision": 0.6,
                "recall": 0.58,
                "f1_score": 0.59,
                "sample_count": 24,
            }
        ]
    )

    app = create_app()
    from backend.api.deps import get_current_user

    app.dependency_overrides[get_current_user] = lambda: {"sub": "test_user", "role": "admin"}
    _override_memory(app, FakeMemory(history=history, ml_history=ml_history))

    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        response = client.get("/api/v1/analytics/metrics")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["closed_trades"] == 1
    assert body["data"]["ml_snapshots"][0]["sample_count"] == 24


def test_metrics_handles_empty_dataset(api_client):
    from fastapi.testclient import TestClient

    from backend.api.deps import get_current_user
    from backend.main import create_app

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: {"sub": "test_user", "role": "admin"}
    _override_memory(app, FakeMemory(history=pd.DataFrame(), ml_history=pd.DataFrame()))

    with TestClient(app) as client:
        response = client.get("/api/v1/analytics/metrics")

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["closed_trades"] == 0
    assert body["data"]["monthly"] == []


def test_metrics_returns_503_on_database_failure(api_client):
    from fastapi.testclient import TestClient

    from backend.api.deps import get_current_user
    from backend.main import create_app

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: {"sub": "test_user", "role": "admin"}
    _override_memory(
        app,
        FakeMemory(error=OperationalError("select 1", {}, RuntimeError("db down"))),
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/analytics/metrics")

    assert response.status_code == 503
    assert response.json()["detail"] == "Analytics database is unavailable."


def test_sentiment_rejects_malformed_state(api_client):
    from fastapi.testclient import TestClient

    from backend.api.deps import get_current_user
    from backend.main import create_app

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: {"sub": "test_user", "role": "admin"}
    _override_memory(app, FakeMemory(state="broken"))

    with TestClient(app) as client:
        response = client.get("/api/v1/analytics/sentiment")

    assert response.status_code == 500
    assert response.json()["detail"] == "Analytics state 'last_sentiment' is malformed."
