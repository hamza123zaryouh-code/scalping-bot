"""Central application configuration for the backend API."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT = Path(__file__).resolve().parents[2]
_DEV_ONLY_SECRET = "DEVELOPMENT_ONLY_SECRET_KEY_DO_NOT_USE_IN_PRODUCTION"
_DEFAULT_DEV_CORS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8501",
    "http://127.0.0.1:8501",
)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = base.copy()
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_platform_config() -> dict[str, Any]:
    app_env = os.getenv("APP_ENV", "development").strip().lower() or "development"
    base = _load_yaml(ROOT / "configs" / "default.yaml")
    override = _load_yaml(ROOT / "configs" / f"{app_env}.yaml")
    return _merge(base, override)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        extra="ignore",
        enable_decoding=False,
    )

    app_env: str = "development"
    app_name: str = "XAUUSD Trading Platform"
    app_version: str = "1.0.0"

    api_host: str = "0.0.0.0"
    api_port: int = 8000

    secret_key: str | None = None
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    auth_admin_username: str | None = None
    auth_admin_password_hash: str | None = None
    allow_insecure_dev_defaults: bool = False
    cors_origins: tuple[str, ...] = Field(default_factory=tuple)
    api_key: str | None = None

    mt5_login: int = 0
    mt5_password: str = ""
    mt5_server: str = ""
    bot_mode: str = "paper"
    allow_live_account: bool = False

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_owner_user_id: str = ""
    telegram_control_api_key: str = ""
    telegram_backend_base_url: str = "http://127.0.0.1:8000"

    ftmo_max_daily_loss: float = 6000.0
    ftmo_max_total_loss: float = 16000.0
    starting_capital: float = 160000.0

    postgres_url: str = ""
    supabase_db_url: str = ""
    supabase_pooler_url: str = ""

    @model_validator(mode="before")
    @classmethod
    def _normalize_raw_values(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values

        app_env = str(values.get("app_env", "development")).strip().lower() or "development"
        values["app_env"] = app_env

        raw_cors = values.get("cors_origins")
        if isinstance(raw_cors, str):
            values["cors_origins"] = tuple(
                origin.strip() for origin in raw_cors.split(",") if origin.strip()
            )

        for key in (
            "secret_key",
            "auth_admin_username",
            "auth_admin_password_hash",
            "api_key",
            "postgres_url",
            "supabase_db_url",
            "supabase_pooler_url",
        ):
            value = values.get(key)
            if isinstance(value, str):
                values[key] = value.strip()

        return values

    @model_validator(mode="after")
    def _validate_security(self) -> Settings:
        allowed_envs = {"development", "test", "staging", "production"}
        if self.app_env not in allowed_envs:
            raise ValueError(f"APP_ENV must be one of {sorted(allowed_envs)}")

        allowed_modes = {"paper", "demo", "live"}
        if self.bot_mode not in allowed_modes:
            raise ValueError(f"BOT_MODE must be one of {sorted(allowed_modes)}")

        if not self.secret_key:
            if self.allow_insecure_dev_defaults and not self.is_production:
                object.__setattr__(self, "secret_key", _DEV_ONLY_SECRET)
            else:
                raise ValueError(
                    "SECRET_KEY is required. For local-only experiments you may set "
                    "ALLOW_INSECURE_DEV_DEFAULTS=true outside production."
                )

        if self.is_production and self.secret_key == _DEV_ONLY_SECRET:
            raise ValueError("SECRET_KEY must not use the development fallback in production.")

        if not self.auth_admin_username:
            raise ValueError("AUTH_ADMIN_USERNAME is required for backend authentication.")

        if not self.auth_admin_password_hash:
            raise ValueError("AUTH_ADMIN_PASSWORD_HASH is required for backend authentication.")

        if self.bot_mode == "live" and not self.allow_live_account:
            raise ValueError("BOT_MODE=live requires ALLOW_LIVE_ACCOUNT=true.")

        if not self.cors_origins:
            if self.is_production:
                raise ValueError("CORS_ORIGINS must be configured in production.")
            object.__setattr__(self, "cors_origins", _DEFAULT_DEV_CORS)

        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def telegram_ready(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def telegram_api_key(self) -> str:
        return self.telegram_control_api_key.strip() or (self.api_key or "").strip()

    @property
    def mt5_ready(self) -> bool:
        return self.mt5_login > 0 and bool(self.mt5_password and self.mt5_server)

    @property
    def database_url(self) -> str:
        if self.postgres_url:
            return self.postgres_url
        if self.supabase_db_url:
            return self.supabase_db_url
        if self.supabase_pooler_url:
            return self.supabase_pooler_url
        return f"sqlite:///{(ROOT / 'autonomous_xauusd.db').as_posix()}"


_platform_cfg: dict[str, Any] = _load_platform_config()


def get_yaml_section(section: str) -> dict[str, Any]:
    return _platform_cfg.get(section, {})


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(_env_file=ROOT / ".env", _env_file_encoding="utf-8")
