from __future__ import annotations

from pathlib import Path

from autonomous_xauusd.settings import load_settings


def test_load_settings_defaults(monkeypatch):
    monkeypatch.setenv("POSTGRES_URL", "")
    monkeypatch.setenv("SUPABASE_DB_URL", "")
    monkeypatch.setenv("SUPABASE_POOLER_URL", "")
    monkeypatch.delenv("AUTONOMOUS_MODE", raising=False)
    monkeypatch.setenv("AUTO_RSI_BUY_THRESHOLD", "58")
    monkeypatch.setenv("AUTO_RSI_SELL_THRESHOLD", "42")

    settings = load_settings(Path.cwd())

    assert settings.mode == "paper"
    assert settings.symbol == "XAUUSD"
    assert settings.default_parameters.rsi_buy_threshold == 58.0
    assert settings.default_parameters.rsi_sell_threshold == 42.0
    assert settings.database_url.startswith("sqlite:///")


def test_load_settings_with_postgres(monkeypatch):
    monkeypatch.setenv("POSTGRES_URL", "postgresql+psycopg://trader:secret@localhost:5432/xauusd")
    settings = load_settings(Path.cwd())
    assert settings.database_url.startswith("postgresql+psycopg://")
