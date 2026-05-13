from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class LiveBotConfig:
    mt5_login: int
    mt5_password: str
    mt5_server: str
    symbol: str
    timeframe: str
    bot_mode: str
    allow_live_account: bool
    check_interval_seconds: int
    history_bars: int
    risk_per_trade: float
    max_lot_size: float
    spread_extra_multiplier: float
    stop_loss_atr_multiplier: float
    take_profit_atr_multiplier: float
    max_open_positions: int
    max_spread_points: float
    max_daily_loss_limit: float
    max_total_loss_limit: float
    safety_daily_buffer: float
    safety_total_buffer: float
    session_start_hour: int
    session_end_hour: int
    magic_number: int
    order_comment: str
    allowed_weekdays: tuple[int, ...]
    telegram_bot_token: str
    telegram_chat_id: str
    status_heartbeat_minutes: int
    send_heartbeat_to_telegram: bool
    max_telegram_messages_per_day: int
    min_volume_multiplier: float
    duplicate_signal_cooldown_minutes: int
    adx_min_strength: float
    break_even_atr_trigger: float

    @property
    def telegram_ready(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def mt5_ready(self) -> bool:
        return self.mt5_login > 0 and bool(self.mt5_password and self.mt5_server)


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


def _env_weekdays(name: str, default: tuple[int, ...]) -> tuple[int, ...]:
    raw = os.getenv(name, "")
    if not raw.strip():
        return default
    values = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            values.append(int(part))
    return tuple(values) if values else default


def load_live_bot_config(base_dir: Path | None = None) -> LiveBotConfig:
    base_dir = base_dir or Path(__file__).resolve().parent
    load_dotenv(base_dir / ".env")

    return LiveBotConfig(
        mt5_login=_env_int("MT5_LOGIN", 0),
        mt5_password=os.getenv("MT5_PASSWORD", "").strip(),
        mt5_server=os.getenv("MT5_SERVER", "").strip(),
        symbol=os.getenv("TRADING_SYMBOL", "XAUUSD").strip() or "XAUUSD",
        timeframe=os.getenv("TRADING_TIMEFRAME", "M1").strip().upper() or "M1",
        bot_mode=os.getenv("BOT_MODE", "paper").strip().lower() or "paper",
        allow_live_account=_env_bool("ALLOW_LIVE_ACCOUNT", False),
        check_interval_seconds=_env_int("CHECK_INTERVAL_SECONDS", 20),
        history_bars=_env_int("HISTORY_BARS", 350),
        risk_per_trade=_env_float("RISK_PER_TRADE", 0.0025),
        max_lot_size=_env_float("MAX_LOT_SIZE", 6.0),
        spread_extra_multiplier=_env_float("SPREAD_EXTRA_MULTIPLIER", 1.0),
        stop_loss_atr_multiplier=_env_float("STOP_LOSS_ATR_MULTIPLIER", 1.5),
        take_profit_atr_multiplier=_env_float("TAKE_PROFIT_ATR_MULTIPLIER", 3.0),
        max_open_positions=_env_int("MAX_OPEN_POSITIONS", 1),
        max_spread_points=_env_float("MAX_SPREAD_POINTS", 350.0),
        max_daily_loss_limit=_env_float("FTMO_MAX_DAILY_LOSS", 8000.0),
        max_total_loss_limit=_env_float("FTMO_MAX_TOTAL_LOSS", 16000.0),
        safety_daily_buffer=_env_float("SAFETY_DAILY_BUFFER", 2500.0),
        safety_total_buffer=_env_float("SAFETY_TOTAL_BUFFER", 4000.0),
        session_start_hour=_env_int("SESSION_START_HOUR", 7),
        session_end_hour=_env_int("SESSION_END_HOUR", 15),
        magic_number=_env_int("MAGIC_NUMBER", 20260511),
        order_comment=os.getenv("ORDER_COMMENT", "FTMO XAUUSD Live Test").strip() or "FTMO XAUUSD Live Test",
        allowed_weekdays=_env_weekdays("ALLOWED_WEEKDAYS", (0, 1, 2, 3, 4)),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
        status_heartbeat_minutes=_env_int("STATUS_HEARTBEAT_MINUTES", 180),
        send_heartbeat_to_telegram=_env_bool("SEND_HEARTBEAT_TO_TELEGRAM", False),
        max_telegram_messages_per_day=_env_int("MAX_TELEGRAM_MESSAGES_PER_DAY", 5),
        min_volume_multiplier=_env_float("MIN_VOLUME_MULTIPLIER", 1.10),
        duplicate_signal_cooldown_minutes=_env_int("DUPLICATE_SIGNAL_COOLDOWN_MINUTES", 45),
        adx_min_strength=_env_float("ADX_MIN_STRENGTH", 22.0),
        break_even_atr_trigger=_env_float("BREAK_EVEN_ATR_TRIGGER", 1.0),
    )
