"""Unit tests for config loading."""
from __future__ import annotations

import pytest

from backend.core.config import Settings


class TestSettings:
    def _base_settings(self, **overrides):
        return {
            "secret_key": "test_secret_key_32_characters_long",
            "auth_admin_username": "admin",
            "auth_admin_password_hash": "$2b$12$123456789012345678901uLckCy13F4M8Aq6fTn6zkRgZNpmjQe7K",
            "cors_origins": ("http://localhost:3000",),
            **overrides,
        }

    def test_default_bot_mode_is_paper(self):
        settings = Settings(**self._base_settings())
        assert settings.bot_mode == "paper"

    def test_invalid_bot_mode_raises(self):
        with pytest.raises(Exception):
            Settings(**self._base_settings(bot_mode="invalid_mode"))

    def test_telegram_ready_false_when_empty(self):
        settings = Settings(**self._base_settings(), telegram_bot_token="", telegram_chat_id="")
        assert settings.telegram_ready is False

    def test_telegram_ready_true_when_set(self):
        settings = Settings(**self._base_settings(), telegram_bot_token="abc", telegram_chat_id="123")
        assert settings.telegram_ready is True

    def test_mt5_ready_false_when_login_zero(self):
        settings = Settings(**self._base_settings(), mt5_login=0, mt5_password="x", mt5_server="x")
        assert settings.mt5_ready is False

    def test_mt5_ready_true_when_complete(self):
        settings = Settings(**self._base_settings(), mt5_login=12345, mt5_password="pass", mt5_server="server.com")
        assert settings.mt5_ready is True

    def test_is_production_flag(self):
        settings = Settings(**self._base_settings(), app_env="production")
        assert settings.is_production is True

    def test_production_requires_secret_key(self, monkeypatch):
        monkeypatch.delenv("SECRET_KEY", raising=False)
        with pytest.raises(ValueError, match="SECRET_KEY is required"):
            Settings(
                app_env="production",
                secret_key="",
                auth_admin_username="admin",
                auth_admin_password_hash="hash",
                cors_origins=("https://example.com",),
            )

    def test_production_requires_cors_origins(self, monkeypatch):
        monkeypatch.delenv("CORS_ORIGINS", raising=False)
        with pytest.raises(ValueError, match="CORS_ORIGINS must be configured"):
            Settings(
                app_env="production",
                secret_key="test_secret_key_32_characters_long",
                auth_admin_username="admin",
                auth_admin_password_hash="hash",
            )

    def test_live_mode_requires_explicit_allowance(self):
        with pytest.raises(ValueError, match="ALLOW_LIVE_ACCOUNT=true"):
            Settings(**self._base_settings(bot_mode="live"))
