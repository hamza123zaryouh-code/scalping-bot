"""Signal and MT5 position service helpers."""
from __future__ import annotations

import json
import logging
from contextlib import suppress
from datetime import datetime
from pathlib import Path

from backend.api.schemas.signals import LiveSignalResponse, OpenPosition
from backend.core.config import get_settings

logger = logging.getLogger(__name__)

STATE_PATH = Path("live_logs/bot_state.json")


class SignalService:
    """Backend service for lightweight signal and position retrieval."""

    def __init__(self) -> None:
        self._settings = get_settings()

    def get_latest_signal(self) -> LiveSignalResponse | None:
        if not STATE_PATH.exists():
            return None
        with suppress(Exception):
            state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            last_trade_time = state.get("last_trade_time")
            if last_trade_time:
                side = "buy" if state.get("last_long_signal_time") == last_trade_time else "sell"
                label = "LONG" if side == "buy" else "SHORT"
                return LiveSignalResponse(
                    side=side,
                    entry_label=label,
                    trigger_time=datetime.fromisoformat(last_trade_time),
                    atr_value=0.0,
                    reference_price=0.0,
                    reason="Latest signal inferred from the live execution state.",
                    regime="unknown",
                    confidence=0.0,
                )
        return None

    def get_open_positions(self) -> list[OpenPosition]:
        try:
            import MetaTrader5 as mt5  # type: ignore
        except ImportError:
            return []

        settings = self._settings
        if not settings.mt5_ready:
            return []

        initialized_here = False
        try:
            account_info = mt5.account_info()
            if account_info is None:
                if not mt5.initialize():
                    logger.warning("MT5 initialize failed while fetching positions: %s", mt5.last_error())
                    return []
                initialized_here = True
                if not mt5.login(settings.mt5_login, password=settings.mt5_password, server=settings.mt5_server):
                    logger.warning("MT5 login failed while fetching positions: %s", mt5.last_error())
                    return []

            positions = mt5.positions_get()
            if positions is None:
                return []

            result: list[OpenPosition] = []
            for position in positions:
                result.append(
                    OpenPosition(
                        ticket=int(position.ticket),
                        symbol=str(position.symbol),
                        side="buy" if int(position.type) == 0 else "sell",
                        volume=float(position.volume),
                        open_price=float(position.price_open),
                        current_price=float(position.price_current),
                        stop_loss=float(position.sl),
                        take_profit=float(position.tp),
                        unrealized_pnl=float(position.profit),
                        open_time=datetime.fromtimestamp(position.time),
                        magic=int(position.magic),
                        comment=str(position.comment),
                    )
                )
            return result
        except Exception as exc:
            logger.warning("Could not fetch MT5 positions: %s", exc)
            return []
        finally:
            if initialized_here:
                with suppress(Exception):
                    mt5.shutdown()
