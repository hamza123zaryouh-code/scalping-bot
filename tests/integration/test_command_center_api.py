from __future__ import annotations


def test_command_center_snapshot_returns_operator_sections(api_client):
    response = api_client.get("/api/v1/dashboard/command-center")
    assert response.status_code == 200

    body = response.json()["data"]
    assert "stream" in body
    assert "runtime" in body
    assert "telegram" in body
    assert "logs" in body
    assert isinstance(body["stream"]["available_channels"], list)
    assert "control_state" in body["runtime"]
    assert "recent_actions" in body["telegram"]
