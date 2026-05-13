"""Integration tests for the FastAPI application."""
from __future__ import annotations

from jose import jwt


class TestHealthEndpoint:
    def test_health_returns_200(self, api_client):
        response = api_client.get("/api/v1/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "healthy"
        assert "version" in body


class TestAuthEndpoint:
    def test_login_with_wrong_password_returns_401(self, strict_api_client):
        response = strict_api_client.post(
            "/api/v1/auth/token",
            data={"username": "admin", "password": "wrong"},
        )
        assert response.status_code == 401

    def test_login_with_correct_password_returns_token(self, strict_api_client):
        response = strict_api_client.post(
            "/api/v1/auth/token",
            data={"username": "admin", "password": "correct-password"},
        )
        assert response.status_code == 200
        assert "access_token" in response.json()

    def test_protected_route_rejects_missing_token(self, strict_api_client):
        response = strict_api_client.get("/api/v1/reports/list")
        assert response.status_code == 401
        assert response.json()["detail"] == "Missing authentication token"

    def test_protected_route_rejects_forged_token(self, strict_api_client):
        forged_token = jwt.encode({"sub": "admin", "role": "admin"}, "wrong-secret", algorithm="HS256")
        response = strict_api_client.get(
            "/api/v1/reports/list",
            headers={"Authorization": f"Bearer {forged_token}"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid authentication token"

    def test_protected_route_rejects_expired_token(self, strict_api_client, expired_token):
        response = strict_api_client.get(
            "/api/v1/reports/list",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Token has expired"


class TestRiskEndpoint:
    def test_ftmo_status_returns_data(self, api_client):
        response = api_client.get(
            "/api/v1/risk/ftmo",
            params={"equity": 160000, "day_start_equity": 160000, "estimated_trade_risk": 400},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert "daily_ok" in data
        assert "risk_level" in data
        assert data["daily_ok"] is True

    def test_risk_level_is_green_when_healthy(self, api_client):
        response = api_client.get(
            "/api/v1/risk/ftmo",
            params={"equity": 160000, "day_start_equity": 160000, "estimated_trade_risk": 400},
        )
        assert response.json()["data"]["risk_level"] == "green"

    def test_risk_level_is_red_when_breached(self, api_client):
        response = api_client.get(
            "/api/v1/risk/ftmo",
            params={"equity": 152100, "day_start_equity": 160000, "estimated_trade_risk": 400},
        )
        data = response.json()["data"]
        assert data["daily_ok"] is False


class TestBacktestEndpoints:
    def test_run_backtest_returns_result(self, api_client):
        payload = {
            "start_date": "2026-01-01",
            "end_date": "2026-05-01",
            "starting_capital": 160000,
            "risk_per_trade": 0.0025,
            "sl_atr_multiplier": 1.5,
            "tp_atr_multiplier": 3.0,
            "max_open_trades": 3,
            "commission": 0.35,
            "symbol": "XAUUSD",
        }
        response = api_client.post("/api/v1/backtest/run", json=payload)
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["metrics"]["total_trades"] > 0
        assert body["data"]["metrics"]["ftmo_passed"] is True
        assert body["data"]["trades"]

    def test_status_and_result_endpoint_return_completed_task(self, api_client):
        payload = {
            "start_date": "2026-01-01",
            "end_date": "2026-05-01",
            "starting_capital": 160000,
            "risk_per_trade": 0.0025,
            "sl_atr_multiplier": 1.5,
            "tp_atr_multiplier": 3.0,
            "max_open_trades": 3,
            "commission": 0.35,
            "symbol": "XAUUSD",
        }
        run_response = api_client.post("/api/v1/backtest/run", json=payload)
        assert run_response.status_code == 200
        task_id = run_response.json()["data"]["task_id"]

        status_response = api_client.get(f"/api/v1/backtest/status/{task_id}")
        assert status_response.status_code == 200
        assert status_response.json()["data"]["status"] == "completed"

        result_response = api_client.get(f"/api/v1/backtest/result/{task_id}")
        assert result_response.status_code == 200
        assert result_response.json()["data"]["task_id"] == task_id


class TestReportsEndpoint:
    def test_list_reports_returns_ok(self, api_client):
        response = api_client.get("/api/v1/reports/list")
        assert response.status_code == 200
        assert "reports" in response.json()["data"]

    def test_download_unknown_file_returns_404(self, api_client):
        response = api_client.get("/api/v1/reports/download/nonexistent.pdf")
        assert response.status_code == 404

    def test_path_traversal_blocked(self, api_client):
        response = api_client.get("/api/v1/reports/download/../config.py")
        assert response.status_code in {400, 404}
