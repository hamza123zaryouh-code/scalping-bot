from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from .models import StrategyParameters


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return int(value.strip())


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return float(value.strip())


def _env_csv_ints(name: str, default: tuple[int, ...]) -> tuple[int, ...]:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return tuple(int(part.strip()) for part in raw.split(",") if part.strip())


@dataclass(frozen=True)
class XAUUSDSettings:
    base_dir: Path
    mode: str
    symbol: str
    timeframe: str
    poll_interval_seconds: int
    history_bars: int
    max_open_positions: int
    max_consecutive_errors: int
    trading_start_hour: int
    trading_end_hour: int
    allowed_weekdays: tuple[int, ...]
    mt5_login: int
    mt5_password: str
    mt5_server: str
    max_slippage_points: int
    magic_number: int
    order_comment: str
    paper_starting_balance: float
    postgres_url: str
    telegram_bot_token: str
    telegram_chat_id: str
    telegram_owner_user_id: str
    telegram_control_api_key: str
    telegram_backend_base_url: str
    train_every_days: int
    daily_report_hour_utc: int
    dashboard_host: str
    dashboard_port: int
    model_artifact_path: Path
    default_parameters: StrategyParameters
    sentiment_symbol: str
    sentiment_cache_minutes: int
    sentiment_filter_threshold: float

    @property
    def mt5_ready(self) -> bool:
        return self.mt5_login > 0 and bool(self.mt5_password and self.mt5_server)

    @property
    def telegram_ready(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def database_url(self) -> str:
        if self.postgres_url:
            return self.postgres_url
        return f"sqlite:///{(self.base_dir / 'autonomous_xauusd.db').as_posix()}"


def load_settings(base_dir: Path | None = None) -> XAUUSDSettings:
    root = base_dir or Path(__file__).resolve().parent.parent
    # override=False: existing env vars (e.g. set by tests) take precedence over .env
    load_dotenv(root / ".env", override=False)

    postgres_url = (
        os.getenv("POSTGRES_URL", "").strip()
        or os.getenv("SUPABASE_DB_URL", "").strip()
        or os.getenv("SUPABASE_POOLER_URL", "").strip()
    )

    symbol = os.getenv("AUTONOMOUS_SYMBOL", os.getenv("TRADING_SYMBOL", "XAUUSD")).strip().upper() or "XAUUSD"
    timeframe = os.getenv("AUTONOMOUS_TIMEFRAME", os.getenv("TRADING_TIMEFRAME", "H1")).strip().upper() or "H1"

    default_parameters = StrategyParameters(
        ema_fast=_env_int("AUTO_EMA_FAST", 8),
        ema_slow=_env_int("AUTO_EMA_SLOW", 21),
        ema_trend=_env_int("AUTO_EMA_TREND", 50),
        rsi_period=_env_int("AUTO_RSI_PERIOD", 14),
        rsi_fast_period=_env_int("AUTO_RSI_FAST_PERIOD", 5),
        atr_period=_env_int("AUTO_ATR_PERIOD", 14),
        volatility_window=_env_int("AUTO_VOLATILITY_WINDOW", 20),
        rsi_buy_threshold=_env_float("AUTO_RSI_BUY_THRESHOLD", 56.0),
        rsi_sell_threshold=_env_float("AUTO_RSI_SELL_THRESHOLD", 44.0),
        rsi_pullback_strong=_env_float("AUTO_RSI_PULLBACK_STRONG", 30.0),
        rsi_pullback_weak=_env_float("AUTO_RSI_PULLBACK_WEAK", 35.0),
        h4_adx_strong=_env_float("AUTO_H4_ADX_STRONG", 26.0),
        h4_adx_weak=_env_float("AUTO_H4_ADX_WEAK", 18.0),
        stop_loss_atr=_env_float("AUTO_STOP_LOSS_ATR", 1.0),
        take_profit_atr=_env_float("AUTO_TAKE_PROFIT_ATR", 3.0),
        risk_per_trade=_env_float("AUTO_RISK_PER_TRADE", _env_float("RISK_PER_TRADE", 0.005)),
        risk_strong_regime=_env_float("AUTO_RISK_STRONG_REGIME", 0.015),
        risk_weak_regime=_env_float("AUTO_RISK_WEAK_REGIME", 0.008),
    )

    mode = os.getenv("AUTONOMOUS_MODE", os.getenv("BOT_MODE", "paper")).strip().lower() or "paper"
    if mode not in {"paper", "demo", "live"}:
        raise ValueError("AUTONOMOUS_MODE/BOT_MODE must be one of: paper, demo, live")

    return XAUUSDSettings(
        base_dir=root,
        mode=mode,
        symbol=symbol,
        timeframe=timeframe,
        poll_interval_seconds=_env_int("AUTO_POLL_INTERVAL_SECONDS", 15),
        history_bars=_env_int("AUTO_HISTORY_BARS", 500),
        max_open_positions=_env_int("AUTO_MAX_OPEN_POSITIONS", 1),
        max_consecutive_errors=_env_int("AUTO_MAX_CONSECUTIVE_ERRORS", 5),
        trading_start_hour=_env_int("AUTO_TRADING_START_HOUR", 6),
        trading_end_hour=_env_int("AUTO_TRADING_END_HOUR", 21),
        allowed_weekdays=_env_csv_ints("AUTO_ALLOWED_WEEKDAYS", (0, 1, 2, 3, 4)),
        mt5_login=_env_int("MT5_LOGIN", 0),
        mt5_password=os.getenv("MT5_PASSWORD", "").strip(),
        mt5_server=os.getenv("MT5_SERVER", "").strip(),
        max_slippage_points=_env_int("AUTO_MAX_SLIPPAGE_POINTS", 30),
        magic_number=_env_int("AUTO_MAGIC_NUMBER", 20260513),
        order_comment=os.getenv("AUTO_ORDER_COMMENT", "Autonomous XAUUSD System").strip() or "Autonomous XAUUSD System",
        paper_starting_balance=_env_float("AUTO_PAPER_START_BALANCE", 10000.0),
        postgres_url=postgres_url,
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
        telegram_owner_user_id=os.getenv("TELEGRAM_OWNER_USER_ID", "").strip(),
        telegram_control_api_key=os.getenv(
            "TELEGRAM_CONTROL_API_KEY",
            os.getenv("API_KEY", os.getenv("SECRET_KEY", "")),
        ).strip(),
        telegram_backend_base_url=os.getenv("TELEGRAM_BACKEND_BASE_URL", "http://127.0.0.1:8000").strip() or "http://127.0.0.1:8000",
        train_every_days=_env_int("AUTO_TRAIN_EVERY_DAYS", 7),
        daily_report_hour_utc=_env_int("AUTO_DAILY_REPORT_HOUR_UTC", 19),
        dashboard_host=os.getenv("AUTO_DASHBOARD_HOST", "127.0.0.1").strip() or "127.0.0.1",
        dashboard_port=_env_int("AUTO_DASHBOARD_PORT", 8502),
        model_artifact_path=root / os.getenv("AUTO_MODEL_ARTIFACT_PATH", "artifacts/xauusd_feedback_model.joblib"),
        default_parameters=default_parameters,
        sentiment_symbol=os.getenv("SENTIMENT_SYMBOL", "GC=F").strip() or "GC=F",
        sentiment_cache_minutes=_env_int("SENTIMENT_CACHE_MINUTES", 30),
        sentiment_filter_threshold=_env_float("SENTIMENT_FILTER_THRESHOLD", 0.5),
    )
