from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from config import LiveBotConfig, load_live_bot_config
from indicators import LiveSignal, derive_live_signal, prepare_live_features
from logger import setup_logger
from risk_manager import (
    FTMOLimits,
    GuardrailDecision,
    build_ftmo_limits,
    calculate_position_size,
    calculate_spread_points,
    is_demo_like_account,
    safe_float,
    validate_ftmo_buffers,
    validate_spread,
    within_trading_window,
)

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover
    mt5 = None


@dataclass
class BotState:
    current_trading_day: str | None = None
    day_start_equity: float = 0.0
    last_processed_bar: str | None = None
    last_long_signal_time: str | None = None
    last_short_signal_time: str | None = None
    last_trade_time: str | None = None
    last_heartbeat_time: str | None = None
    last_report_time: str | None = None
    telegram_day: str | None = None
    telegram_messages_sent: int = 0


@dataclass
class RuntimeStats:
    processed_cycles: int = 0
    new_signals: int = 0
    blocked_signals: int = 0
    executed_orders: int = 0
    paper_orders: int = 0
    no_signal_bars: int = 0
    error_count: int = 0
    last_action: str = "gestart"


class LiveTradingBot:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or Path(__file__).resolve().parent
        self.config = load_live_bot_config(self.base_dir)
        self.log_dir = self.base_dir / "live_logs"
        self.logger = setup_logger("xauusd_live_bot", self.log_dir)
        self.state_path = self.log_dir / "bot_state.json"
        self.state = self._load_state()
        self.limits = build_ftmo_limits(
            start_capital=160000.0,
            max_daily_loss=self.config.max_daily_loss_limit,
            max_total_loss=self.config.max_total_loss_limit,
        )
        self.timeframe = self._resolve_timeframe(self.config.timeframe)
        self.runtime_stats = RuntimeStats()

    def _resolve_timeframe(self, timeframe_name: str) -> int:
        if mt5 is None:
            return -1
        mapping = {
            "M1": mt5.TIMEFRAME_M1,
            "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15,
            "M30": mt5.TIMEFRAME_M30,
            "H1": mt5.TIMEFRAME_H1,
        }
        if timeframe_name not in mapping:
            raise ValueError(f"Unsupported timeframe: {timeframe_name}")
        return mapping[timeframe_name]

    def _load_state(self) -> BotState:
        if not self.state_path.exists():
            return BotState()
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            return BotState(**data)
        except Exception as exc:
            self.logger.warning("Could not read bot state, starting clean: %s", exc)
            return BotState()

    def _save_state(self) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state.__dict__, indent=2), encoding="utf-8")

    def _reset_telegram_counter_if_needed(self, now: datetime) -> None:
        day_key = now.date().isoformat()
        if self.state.telegram_day != day_key:
            self.state.telegram_day = day_key
            self.state.telegram_messages_sent = 0
            self._save_state()

    def notify(self, message: str, count_toward_daily_limit: bool = True) -> bool:
        dutch_message = self._to_dutch_message(message)
        self.logger.info(dutch_message)
        if not self.config.telegram_ready:
            return False

        now = datetime.now()
        self._reset_telegram_counter_if_needed(now)
        sent_today = int(self.state.telegram_messages_sent)
        if count_toward_daily_limit and sent_today >= self.config.max_telegram_messages_per_day:
            self.logger.info(
                "Telegram routine message skipped due to daily cap (%s/%s)",
                sent_today,
                self.config.max_telegram_messages_per_day,
            )
            return False
        try:
            response = requests.post(
                f"https://api.telegram.org/bot{self.config.telegram_bot_token}/sendMessage",
                data={"chat_id": self.config.telegram_chat_id, "text": dutch_message},
                timeout=20,
            )
            response.raise_for_status()
            if count_toward_daily_limit:
                self.state.telegram_messages_sent = sent_today + 1
                self._save_state()
            return True
        except Exception as exc:  # pragma: no cover - network dependent
            self.logger.warning("Telegram notification failed: %s", exc)
            return False

    def _to_dutch_message(self, message: str) -> str:
        translated = message
        replacements = [
            ("Live bot failed to connect to MT5", "Live bot kon geen verbinding maken met MT5"),
            ("Live bot starting", "Live bot gestart"),
            ("Live bot stopped", "Live bot gestopt"),
            ("Live bot stopped unexpectedly", "Live bot onverwacht gestopt"),
            ("ORDER ATTEMPT", "ORDER POGING"),
            ("ORDER EXECUTED", "ORDER UITGEVOERD"),
            ("PAPER TRADE", "PAPER TRADE"),
            ("SIGNAL BLOCKED", "SIGNAAL GEBLOKKEERD"),
            ("Heartbeat", "Statusupdate"),
            ("BOT ERROR", "BOT FOUT"),
            ("Signal ignored due to duplicate cooldown", "Signaal genegeerd door duplicate cooldown"),
            ("No new qualified signal on bar close", "Geen nieuw gekwalificeerd signaal bij bar-close"),
            ("mode=", "modus="),
            ("symbol=", "symbool="),
            ("timeframe=", "timeframe="),
            ("balance=", "saldo="),
            ("equity=", "equity="),
            ("positions=", "posities="),
            ("spread=", "spread="),
            ("open positions limit reached", "limiet open posities bereikt"),
            ("reason=", "reden="),
            ("volume=", "volume="),
            ("price=", "prijs="),
            ("spread_buffer=", "spread_buffer="),
        ]
        for old, new in replacements:
            translated = translated.replace(old, new)
        return translated

    def _should_send_periodic_report(self, now: datetime) -> bool:
        if not self.state.last_report_time:
            return True
        previous = pd.Timestamp(self.state.last_report_time).to_pydatetime()
        return now - previous >= timedelta(hours=2)

    def _send_periodic_report(self, account_info: Any, open_positions: list[Any], spread_points: float) -> None:
        equity = safe_float(getattr(account_info, "equity", 0.0))
        balance = safe_float(getattr(account_info, "balance", 0.0))
        report = (
            "2-uurs rapport\n"
            f"Status: bot actief | modus={self.config.bot_mode} | symbool={self.config.symbol} | timeframe={self.config.timeframe}\n"
            f"Wat heeft hij gedaan: checks={self.runtime_stats.processed_cycles}, signalen={self.runtime_stats.new_signals}, "
            f"geen-signaal bars={self.runtime_stats.no_signal_bars}, blokkades={self.runtime_stats.blocked_signals}, "
            f"uitgevoerde orders={self.runtime_stats.executed_orders}, paper orders={self.runtime_stats.paper_orders}, fouten={self.runtime_stats.error_count}\n"
            f"Huidige stand: saldo={balance:.2f} | equity={equity:.2f} | open posities={len(open_positions)} | spread={spread_points:.1f}\n"
            f"Laatste actie: {self.runtime_stats.last_action}\n"
            "Plan komende 2 uur: markt monitoren, wachten op geldig signaal, risico-limieten bewaken, order plaatsen bij kwalificatie."
        )
        self.notify(report, count_toward_daily_limit=False)
        self.state.last_report_time = datetime.now().isoformat()
        self._save_state()

    def connect(self) -> bool:
        if mt5 is None:
            self.logger.error("MetaTrader5 package is not installed.")
            return False
        if not self.config.mt5_ready:
            self.logger.error("MT5 credentials missing in .env.")
            return False
        if not mt5.initialize():
            self.logger.error("MT5 initialize failed: %s", mt5.last_error())
            return False
        if not mt5.login(self.config.mt5_login, password=self.config.mt5_password, server=self.config.mt5_server):
            self.logger.error("MT5 login failed: %s", mt5.last_error())
            mt5.shutdown()
            return False
        symbol_ok = mt5.symbol_select(self.config.symbol, True)
        if not symbol_ok:
            self.logger.error("Could not select symbol %s", self.config.symbol)
            mt5.shutdown()
            return False
        self.logger.info("Connected to MT5 account %s on %s", self.config.mt5_login, self.config.mt5_server)
        return True

    def shutdown(self) -> None:
        if mt5 is not None:
            mt5.shutdown()

    def get_account_info(self) -> Any:
        return mt5.account_info() if mt5 is not None else None

    def ensure_account_mode_allowed(self) -> GuardrailDecision:
        account_info = self.get_account_info()
        if self.config.bot_mode == "paper":
            return GuardrailDecision(True, "Paper mode active")
        if self.config.bot_mode == "demo":
            return is_demo_like_account(account_info, allow_live_account=False)
        if self.config.bot_mode == "live":
            return is_demo_like_account(account_info, allow_live_account=self.config.allow_live_account)
        return GuardrailDecision(False, f"Unsupported BOT_MODE: {self.config.bot_mode}")

    def fetch_market_data(self) -> pd.DataFrame:
        rates = mt5.copy_rates_from_pos(self.config.symbol, self.timeframe, 0, self.config.history_bars)
        if rates is None:
            raise RuntimeError(f"MT5 returned no rates: {mt5.last_error()}")
        frame = pd.DataFrame(rates)
        if frame.empty:
            return frame
        frame["time"] = pd.to_datetime(frame["time"], unit="s")
        frame = frame.rename(columns={"tick_volume": "volume"})
        if "volume" not in frame.columns:
            frame["volume"] = 0.0
        if "spread" not in frame.columns:
            frame["spread"] = 0.0
        frame = frame[["time", "open", "high", "low", "close", "volume", "spread"]].copy()
        frame = frame.set_index("time").sort_index()
        return frame

    def get_open_positions(self) -> list[Any]:
        positions = mt5.positions_get(symbol=self.config.symbol)
        return list(positions) if positions else []

    def get_latest_tick(self) -> Any:
        return mt5.symbol_info_tick(self.config.symbol)

    def get_symbol_info(self) -> Any:
        return mt5.symbol_info(self.config.symbol)

    def _ensure_day_state(self, equity: float, now: datetime) -> None:
        day_key = now.date().isoformat()
        if self.state.current_trading_day != day_key:
            self.state.current_trading_day = day_key
            self.state.day_start_equity = equity
            self.logger.info("New trading day state initialized at equity %.2f", equity)
            self._save_state()
        self._reset_telegram_counter_if_needed(now)

    def _parse_timestamp(self, value: str | None) -> pd.Timestamp | None:
        if not value:
            return None
        return pd.Timestamp(value)

    def _is_new_closed_bar(self, enriched: pd.DataFrame) -> bool:
        if len(enriched) < 3:
            return False
        last_closed_bar = pd.Timestamp(enriched.index[-2]).isoformat()
        if self.state.last_processed_bar == last_closed_bar:
            return False
        self.state.last_processed_bar = last_closed_bar
        self._save_state()
        return True

    def _should_send_heartbeat(self, now: datetime) -> bool:
        if not self.state.last_heartbeat_time:
            return True
        previous = pd.Timestamp(self.state.last_heartbeat_time).to_pydatetime()
        return now - previous >= timedelta(minutes=self.config.status_heartbeat_minutes)

    def _send_heartbeat(self, account_info: Any, open_positions: list[Any], spread_points: float) -> None:
        equity = safe_float(getattr(account_info, "equity", 0.0))
        balance = safe_float(getattr(account_info, "balance", 0.0))
        message = (
            f"Heartbeat | mode={self.config.bot_mode} | symbol={self.config.symbol} | "
            f"balance={balance:.2f} | equity={equity:.2f} | positions={len(open_positions)} | spread={spread_points:.1f}"
        )
        self.logger.info(message)
        if self.config.send_heartbeat_to_telegram:
            self.notify(message, count_toward_daily_limit=True)
        self.state.last_heartbeat_time = datetime.now().isoformat()
        self._save_state()

    def _signal_blocked_by_cooldown(self, signal: LiveSignal) -> bool:
        if not self.state.last_trade_time:
            return False
        last_trade_time = pd.Timestamp(self.state.last_trade_time)
        return signal.trigger_time <= last_trade_time + pd.Timedelta(minutes=self.config.duplicate_signal_cooldown_minutes)

    def evaluate_signal(self, enriched: pd.DataFrame) -> LiveSignal | None:
        return derive_live_signal(
            enriched=enriched,
            last_long_signal_time=self._parse_timestamp(self.state.last_long_signal_time),
            last_short_signal_time=self._parse_timestamp(self.state.last_short_signal_time),
            min_volume_multiplier=self.config.min_volume_multiplier,
            adx_min_strength=self.config.adx_min_strength,
        )

    def _manage_open_positions(self, open_positions: list[Any], tick: Any, symbol_info: Any, current_atr: float) -> None:
        if not open_positions or current_atr <= 0 or tick is None or mt5 is None:
            return
        ask = safe_float(getattr(tick, "ask", 0.0))
        bid = safe_float(getattr(tick, "bid", 0.0))
        point = safe_float(getattr(symbol_info, "point", 0.0))
        digits = int(getattr(symbol_info, "digits", 2))
        if point <= 0:
            return
        be_trigger_distance = self.config.break_even_atr_trigger * current_atr
        # Small buffer above break-even to cover spread on exit
        be_buffer = round(safe_float(getattr(symbol_info, "spread", 3.0), 3.0) * point * 2, digits)

        for pos in open_positions:
            ticket = getattr(pos, "ticket", 0)
            entry_price = safe_float(getattr(pos, "price_open", 0.0))
            current_sl = safe_float(getattr(pos, "sl", 0.0))
            pos_type = getattr(pos, "type", -1)  # 0=buy, 1=sell

            if pos_type == 0:  # buy position
                profit_distance = bid - entry_price
                new_sl = round(entry_price + be_buffer, digits)
                if profit_distance >= be_trigger_distance and current_sl < new_sl:
                    self._modify_position_sl(ticket, new_sl)
            elif pos_type == 1:  # sell position
                profit_distance = entry_price - ask
                new_sl = round(entry_price - be_buffer, digits)
                if profit_distance >= be_trigger_distance and (current_sl == 0.0 or current_sl > new_sl):
                    self._modify_position_sl(ticket, new_sl)

    def _modify_position_sl(self, ticket: int, new_sl: float) -> None:
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "sl": new_sl,
        }
        result = mt5.order_send(request)
        if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
            self.logger.info("Break-even SL ingesteld | ticket=%s nieuwe_sl=%.2f", ticket, new_sl)
            self.notify(f"Break-even SL ingesteld | ticket={ticket} | nieuwe_sl={new_sl:.2f}", count_toward_daily_limit=False)
        else:
            retcode = result.retcode if result is not None else "None"
            self.logger.warning("SL aanpassing mislukt | ticket=%s retcode=%s", ticket, retcode)

    def _estimate_trade_risk(self, equity: float) -> float:
        return equity * self.config.risk_per_trade

    def _update_signal_state(self, signal: LiveSignal) -> None:
        if signal.side == "buy":
            self.state.last_long_signal_time = signal.trigger_time.isoformat()
        else:
            self.state.last_short_signal_time = signal.trigger_time.isoformat()
        self.state.last_trade_time = signal.trigger_time.isoformat()
        self._save_state()

    def _build_order_request(self, signal: LiveSignal, tick: Any, symbol_info: Any, equity: float) -> dict[str, Any]:
        point = safe_float(getattr(symbol_info, "point", 0.0))
        digits = int(getattr(symbol_info, "digits", 2))
        base_stop_distance = self.config.stop_loss_atr_multiplier * signal.atr_value
        base_take_profit_distance = self.config.take_profit_atr_multiplier * signal.atr_value
        spread_points = calculate_spread_points(tick, symbol_info)
        spread_price = safe_float(spread_points, 0.0) * point
        spread_buffer = max(spread_price * self.config.spread_extra_multiplier, 0.0)
        stop_distance = base_stop_distance + spread_buffer
        take_profit_distance = base_take_profit_distance + spread_buffer
        if spread_buffer > 0:
            self.logger.info(
                "Spread-buffer toegepast: spread=%.1f punten, buffer=%.2f",
                safe_float(spread_points, 0.0),
                spread_buffer,
            )

        volume = calculate_position_size(equity, self.config.risk_per_trade, stop_distance, symbol_info)
        if volume > self.config.max_lot_size:
            self.logger.info("Lotsize capped: %.2f -> %.2f", volume, self.config.max_lot_size)
            volume = round(self.config.max_lot_size, 2)
        if volume <= 0:
            raise ValueError("Calculated volume is zero; order blocked")

        if signal.side == "buy":
            price = safe_float(getattr(tick, "ask", 0.0))
            sl = round(price - stop_distance, digits)
            tp = round(price + take_profit_distance, digits)
            order_type = mt5.ORDER_TYPE_BUY
        else:
            price = safe_float(getattr(tick, "bid", 0.0))
            sl = round(price + stop_distance, digits)
            tp = round(price - take_profit_distance, digits)
            order_type = mt5.ORDER_TYPE_SELL

        if price <= 0 or point <= 0:
            raise ValueError("Invalid symbol price metadata")

        return {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.config.symbol,
            "volume": volume,
            "type": order_type,
            "price": round(price, digits),
            "sl": sl,
            "tp": tp,
            "spread_buffer": round(spread_buffer, digits),
            "deviation": 20,
            "magic": self.config.magic_number,
            "comment": self.config.order_comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": getattr(mt5, "ORDER_FILLING_FOK", 0),
        }

    def _place_or_simulate_order(self, signal: LiveSignal, tick: Any, symbol_info: Any, equity: float) -> None:
        request = self._build_order_request(signal, tick, symbol_info, equity)
        self.runtime_stats.new_signals += 1
        summary = (
            f"{signal.entry_label} signal | mode={self.config.bot_mode} | "
            f"volume={request['volume']:.2f} | price={request['price']:.2f} | "
            f"SL={request['sl']:.2f} | TP={request['tp']:.2f} | spread_buffer={request['spread_buffer']:.2f} | reason={signal.reason}"
        )

        if self.config.bot_mode == "paper":
            self.notify(f"PAPER TRADE | {summary}", count_toward_daily_limit=False)
            self.runtime_stats.paper_orders += 1
            self.runtime_stats.last_action = f"paper order geplaatst ({signal.entry_label})"
            self._update_signal_state(signal)
            return

        self.notify(f"ORDER ATTEMPT | {summary}", count_toward_daily_limit=False)

        result = mt5.order_send(request)
        if result is None:
            raise RuntimeError(f"order_send returned None: {mt5.last_error()} | {summary}")
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            raise RuntimeError(f"Order rejected: retcode={result.retcode} comment={result.comment} | {summary}")

        self.notify(f"ORDER EXECUTED | {summary}", count_toward_daily_limit=False)
        self.runtime_stats.executed_orders += 1
        self.runtime_stats.last_action = f"order uitgevoerd ({signal.entry_label})"
        self._update_signal_state(signal)

    def process_once(self) -> None:
        now = datetime.now()
        self.runtime_stats.processed_cycles += 1
        account_mode = self.ensure_account_mode_allowed()
        if not account_mode.allowed:
            raise RuntimeError(account_mode.reason)

        account_info = self.get_account_info()
        if account_info is None:
            raise RuntimeError("MT5 account info unavailable")
        equity = safe_float(getattr(account_info, "equity", 0.0), safe_float(getattr(account_info, "balance", 0.0), 0.0))
        self._ensure_day_state(equity, now)

        market_data = self.fetch_market_data()
        enriched = prepare_live_features(market_data)
        if enriched.empty:
            self.logger.info("No market data available yet")
            return

        tick = self.get_latest_tick()
        symbol_info = self.get_symbol_info()
        spread_points = calculate_spread_points(tick, symbol_info)
        open_positions = self.get_open_positions()

        if self._should_send_heartbeat(now):
            self._send_heartbeat(account_info, open_positions, spread_points)

        if self._should_send_periodic_report(now):
            self._send_periodic_report(account_info, open_positions, spread_points)

        # Break-even management runs every cycle (not just on new bar)
        current_atr = safe_float(enriched.iloc[-1].get("atr14", 0.0)) if not enriched.empty else 0.0
        if self.config.bot_mode != "paper":
            self._manage_open_positions(open_positions, tick, symbol_info, current_atr)

        if not self._is_new_closed_bar(enriched):
            return

        time_guard = within_trading_window(now, self.config.allowed_weekdays, self.config.session_start_hour, self.config.session_end_hour)
        if not time_guard.allowed:
            self.logger.info(time_guard.reason)
            self.runtime_stats.blocked_signals += 1
            self.runtime_stats.last_action = f"geen entry: {time_guard.reason}"
            return

        spread_guard = validate_spread(spread_points, self.config.max_spread_points)
        if not spread_guard.allowed:
            self.logger.warning(spread_guard.reason)
            self.runtime_stats.blocked_signals += 1
            self.runtime_stats.last_action = f"geen entry: {spread_guard.reason}"
            return

        signal = self.evaluate_signal(enriched)
        if signal is None:
            self.logger.info("No new qualified signal on bar close")
            self.runtime_stats.no_signal_bars += 1
            self.runtime_stats.last_action = "geen nieuw gekwalificeerd signaal"
            return

        if self._signal_blocked_by_cooldown(signal):
            self.logger.info("Signal ignored due to duplicate cooldown")
            self.runtime_stats.blocked_signals += 1
            self.runtime_stats.last_action = "signaal geblokkeerd door cooldown"
            return

        if len(open_positions) >= self.config.max_open_positions:
            self.runtime_stats.blocked_signals += 1
            self.runtime_stats.last_action = "signaal geblokkeerd door open-positie limiet"
            self.notify(
                f"SIGNAL BLOCKED | {signal.entry_label} | open positions limit reached ({len(open_positions)})",
                count_toward_daily_limit=True,
            )
            return

        estimated_trade_risk = self._estimate_trade_risk(equity)
        ftmo_guard = validate_ftmo_buffers(
            equity=equity,
            day_start_equity=self.state.day_start_equity or equity,
            limits=self.limits,
            estimated_trade_risk=estimated_trade_risk,
            safety_daily_buffer=self.config.safety_daily_buffer,
            safety_total_buffer=self.config.safety_total_buffer,
        )
        if not ftmo_guard.allowed:
            self.runtime_stats.blocked_signals += 1
            self.runtime_stats.last_action = f"signaal geblokkeerd door FTMO-buffer: {ftmo_guard.reason}"
            self.notify(
                f"SIGNAL BLOCKED | {signal.entry_label} | {ftmo_guard.reason}",
                count_toward_daily_limit=True,
            )
            return

        self._place_or_simulate_order(signal, tick, symbol_info, equity)

    def run(self) -> None:
        stop_reason = "onbekend"
        self.notify(
            f"Live bot starting | mode={self.config.bot_mode} | symbol={self.config.symbol} | timeframe={self.config.timeframe}",
            count_toward_daily_limit=True,
        )
        if not self.connect():
            stop_reason = "connectie met MT5 mislukt"
            self.notify("Live bot failed to connect to MT5", count_toward_daily_limit=False)
            self.notify(f"Live bot stopped | reason={stop_reason}", count_toward_daily_limit=False)
            return
        try:
            while True:
                try:
                    self.process_once()
                except Exception as exc:
                    self.runtime_stats.error_count += 1
                    self.runtime_stats.last_action = f"fout: {exc}"
                    self.logger.exception("Processing cycle failed")
                    self.notify(f"BOT ERROR | {exc}", count_toward_daily_limit=False)
                time.sleep(self.config.check_interval_seconds)
        except KeyboardInterrupt:
            stop_reason = "gestopt door gebruiker"
            self.notify("Live bot stopped by user", count_toward_daily_limit=False)
        except Exception as exc:
            stop_reason = f"fatale fout: {exc}"
            self.logger.exception("Live bot stopped unexpectedly")
            self.notify(f"Live bot stopped unexpectedly | reason={exc}", count_toward_daily_limit=False)
        finally:
            self.shutdown()
            self.logger.info("MT5 connection closed")
            self.notify(f"Live bot stopped | reason={stop_reason}", count_toward_daily_limit=False)


def run_bot() -> None:
    bot = LiveTradingBot()
    bot.run()


if __name__ == "__main__":
    run_bot()
