from __future__ import annotations

from pathlib import Path


def _headers() -> dict[str, str]:
    return {"X-API-Key": "test_secret_key_32_characters_long"}


def test_telegram_status_requires_api_key(strict_api_client):
    response = strict_api_client.get("/api/v1/telegram/status")
    assert response.status_code == 403
    assert response.json()["detail"] == "Invalid Telegram control API key"


def test_telegram_status_returns_dashboard_snapshot(api_client):
    response = api_client.get("/api/v1/telegram/status", headers=_headers())
    assert response.status_code == 200
    body = response.json()["data"]
    assert "summary" in body
    assert "equity" in body
    assert "ftmo_status" in body


def test_dangerous_control_requires_confirmation(api_client):
    payload = {"telegram_user_id": "999", "telegram_username": "hamza", "confirmed": False}
    response = api_client.post("/api/v1/telegram/control/emergency_stop", json=payload, headers=_headers())
    assert response.status_code == 200
    result = response.json()["data"]
    assert result["requires_confirmation"] is True
    assert result["status"] == "confirmation_required"


def test_control_command_is_enqueued_after_confirmation(api_client):
    payload = {"telegram_user_id": "999", "telegram_username": "hamza", "confirmed": True}
    response = api_client.post("/api/v1/telegram/control/close_all_positions", json=payload, headers=_headers())
    assert response.status_code == 200
    result = response.json()["data"]
    assert result["status"] == "accepted"
    assert result["command_id"] is not None


def test_signal_toggle_updates_control_state(api_client):
    payload = {"telegram_user_id": "999", "telegram_username": "hamza", "enabled": False}
    response = api_client.post("/api/v1/telegram/signals/toggle", json=payload, headers=_headers())
    assert response.status_code == 200
    result = response.json()["data"]
    assert result["enabled"] is False
    assert result["control_state"]["signals_enabled"] is False


def test_export_trade_log_creates_csv(api_client):
    payload = {"telegram_user_id": "999", "telegram_username": "hamza", "confirmed": True}
    response = api_client.post("/api/v1/telegram/reports/export-trade-log", json=payload, headers=_headers())
    assert response.status_code == 200
    data = response.json()["data"]["data"]
    export_path = Path(data["path"])
    assert export_path.exists()
    assert export_path.suffix == ".csv"


def test_quick_backtest_endpoint_uses_backend_service(api_client, monkeypatch):
    from backend.api.routes import telegram as telegram_route

    monkeypatch.setattr(
        telegram_route._service,
        "run_quick_backtest",
        lambda telegram_user_id, telegram_username=None: {
            "summary": "Quick Backtest klaar",
            "result": {"task_id": "bt-1", "metrics": {"total_trades": 12}},
        },
    )
    payload = {"telegram_user_id": "999", "telegram_username": "hamza", "confirmed": True}
    response = api_client.post("/api/v1/telegram/backtest/quick-run", json=payload, headers=_headers())
    assert response.status_code == 200
    assert response.json()["data"]["summary"] == "Quick Backtest klaar"
