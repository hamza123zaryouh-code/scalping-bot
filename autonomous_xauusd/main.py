from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from core.circuit_breaker_singleton import get_circuit_breaker
from core.strategy_engine import get_symbol_cfg, SYMBOL_SPECS

# Gecorreleerde groep: EURUSD en GBPUSD bewegen sterk samen (beide USD major pairs)
_CORRELATED_GROUP: frozenset[str] = frozenset({"EURUSD", "GBPUSD"})
from core.config_watcher import StrategyConfigManager
from core.ftmo_guard import FTMOConfig, FTMOGuard, get_ftmo_guard
from core.sentiment_engine import SentimentEngine
from core.session_engine import SessionEngine

from .analytics_engine import compute_report
from .brain_layer import IntelligenceLayer
from .communication_layer import TelegramControlLayer
from .core.live_news_engine import LiveNewsEngine
from .core.news_guard import NewsGuard
from .core.pattern_memory_engine import PatternMemoryEngine
from .data_layer import DataExecutionLayer
from .memory_layer import MemoryLayer
from .models import SentimentScore, TrainingOutcome
from .settings import XAUUSDSettings, load_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)

_BOT_STATE_PATH = Path("live_logs/bot_state.json")


class AutonomousTradingSystem:
    def __init__(self, settings: XAUUSDSettings | None = None) -> None:
        self.settings = settings or load_settings()
        self.memory = MemoryLayer(self.settings.database_url)
        self.memory.initialize()
        self.parameters = self.memory.load_strategy_parameters(self.settings.default_parameters)
        self.memory.save_strategy_parameters(self.parameters, source="bootstrap")
        _existing_control = self.memory.get_runtime_state("bot_control")
        if _existing_control is None:
            self.memory.set_bot_control_state(
                bot_active=True,
                trading_paused=False,
                signals_enabled=True,
                emergency_stop=False,
            )
        else:
            logger.info(
                "Bot state preserved across restart — active=%s emergency_stop=%s paused=%s",
                _existing_control.get("bot_active"),
                _existing_control.get("emergency_stop"),
                _existing_control.get("trading_paused"),
            )

        self.brain = IntelligenceLayer(self.settings.model_artifact_path)
        self.engine = DataExecutionLayer(self.settings)
        self.sentiment = SentimentEngine(cache_minutes=self.settings.sentiment_cache_minutes)
        self.circuit_breaker = get_circuit_breaker()
        self.session_engine = SessionEngine()
        self.config_manager = StrategyConfigManager()
        self.config_manager.start()

        # Production intelligence layers
        self._news_engine = LiveNewsEngine()
        self._news_guard = NewsGuard(news_engine=self._news_engine)
        self._pattern_memory = PatternMemoryEngine()
        self._ftmo_guard: FTMOGuard = get_ftmo_guard(
            FTMOConfig(
                start_capital=self.settings.ftmo_start_capital,
                max_daily_loss=self.settings.ftmo_max_daily_loss,
                max_weekly_loss=self.settings.ftmo_max_weekly_loss,
                max_total_drawdown=self.settings.ftmo_max_total_drawdown,
                daily_buffer=self.settings.ftmo_daily_buffer,
            )
        )

        # Herstel CB-state na crash of herstart zodat daglimieten intact blijven
        _saved_cb = self.memory.load_circuit_breaker_state()
        if _saved_cb:
            self.circuit_breaker.restore_persistent_state(_saved_cb)

        self.stop_requested = False
        self.consecutive_errors = 0
        self.last_processed_bar: dict[str, str | None] = {}  # per symbool
        self._open_trade_patterns: dict[str, tuple[str, str, str, str]] = {}  # ticket → (sig_type, side, h4_regime, session)

        self._started_at = datetime.now(timezone.utc)
        self._restart_requested = False

        self.telegram = TelegramControlLayer(
            token=self.settings.telegram_bot_token,
            chat_id=self.settings.telegram_chat_id,
            owner_user_id=self.settings.telegram_owner_user_id,
            backend_api_key=self.settings.telegram_control_api_key,
            backend_base_url=self.settings.telegram_backend_base_url,
            status_callback=self._status_text,
            stop_callback=self.request_stop,
            train_callback=self.train_now,
            ping_callback=self._ping_text,
            logs_callback=self._logs_text,
            heat_callback=self._heat_text,
            restart_callback=self.request_restart,
        )

    def request_stop(self) -> str:
        self.memory.set_bot_control_state(bot_active=False, trading_paused=True, emergency_stop=True)
        return "Emergency stop geactiveerd. Nieuwe trades zijn geblokkeerd."

    def train_now(self) -> str:
        outcome = self._run_training_cycle()
        if outcome is None:
            return "Training overgeslagen: nog niet genoeg gesloten trades in de database."
        return (
            f"Model hertraind op {outcome.sample_count} trades. "
            f"Accuracy={outcome.accuracy:.2%}, nieuwe overrides={outcome.parameter_overrides or 'geen'}"
        )

    def _ping_text(self) -> str:
        now = datetime.now(timezone.utc)
        uptime = now - self._started_at
        hours, rem = divmod(int(uptime.total_seconds()), 3600)
        mins = rem // 60
        runtime = self.memory.get_runtime_state("engine_status") or {}
        status = runtime.get("status", "onbekend")
        equity = float(runtime.get("equity", 0.0))
        open_pos = int(runtime.get("open_positions", 0))
        return (
            f"PONG — Bot is actief\n"
            f"Status:   {status}\n"
            f"Uptime:   {hours}u {mins}m\n"
            f"Equity:   EUR {equity:,.2f}\n"
            f"Posities: {open_pos} open\n"
            f"Tijd:     {now.strftime('%d %b %H:%M:%S')} UTC"
        )

    def _logs_text(self, n_lines: int = 40) -> str:
        log_path = Path("live_logs/runtime.log")
        if not log_path.exists():
            return "Geen logbestand gevonden (live_logs/runtime.log)."
        try:
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            recent = lines[-n_lines:] if len(lines) > n_lines else lines
            return "LAATSTE LOGS\n" + "\n".join(recent)
        except Exception as exc:
            return f"Logbestand kon niet worden gelezen: {exc}"

    def _heat_text(self) -> str:
        runtime = self.memory.get_runtime_state("engine_status") or {}
        equity = float(runtime.get("equity", 0.0))
        if equity <= 0:
            return "Equity niet beschikbaar — kan heat niet berekenen."
        heat = self._compute_portfolio_heat(equity)
        max_heat = self.settings.max_portfolio_heat
        status_icon = "VEILIG" if heat < max_heat * 0.7 else ("WAARSCHUWING" if heat < max_heat else "KRITIEK")
        open_risks = []
        for sym in self.settings.symbols:
            from core.strategy_engine import SYMBOL_SPECS
            lot_factor = float(SYMBOL_SPECS.get(sym, {}).get("lot_factor", 100))
            for trade in self.memory.list_open_trades(sym):
                sl_dist = abs(float(trade.get("entry_price", 0)) - float(trade.get("stop_loss", 0)))
                vol = float(trade.get("volume", 0))
                risk_eur = sl_dist * vol * lot_factor
                open_risks.append(f"  {sym} {trade.get('side','?')} {vol}L → EUR {risk_eur:,.0f} risico")
        lines = [
            f"PORTFOLIO HEAT: {heat:.2%} / {max_heat:.0%} max — {status_icon}",
            f"Equity: EUR {equity:,.2f}",
            "",
            f"Open posities ({len(open_risks)}):",
        ] + (open_risks if open_risks else ["  Geen open posities"])
        return "\n".join(lines)

    def request_restart(self) -> str:
        self.memory.set_bot_control_state(bot_active=False, trading_paused=True, emergency_stop=True)
        self.stop_requested = True
        self._restart_requested = True
        return "Herstart gevraagd. Bot stopt en wordt opnieuw gestart door watchdog."

    def _status_text(self) -> str:
        runtime = self.memory.get_runtime_state("engine_status") or {}
        sentiment = self.memory.get_runtime_state("last_sentiment") or {}
        cb = self.circuit_breaker.get_status_summary()
        session = self.session_engine.get_session_info()
        control = self.memory.get_bot_control_state()
        symbol = runtime.get("symbol", self.settings.symbol)
        timeframe = runtime.get("timeframe", self.settings.timeframe)
        cb_status = "ACTIVE" if cb.get("circuit_breaker_active") else "OK"
        cb_description = cb.get("circuit_description", "")
        return (
            f"V22 Status: {runtime.get('status', 'idle')}\n"
            f"Mode: {runtime.get('mode', self.settings.mode)}\n"
            f"Symbool: {symbol} {timeframe}\n"
            f"Open posities: {runtime.get('open_positions', 0)}\n"
            f"Equity: EUR {runtime.get('equity', 0.0):,.2f}\n"
            f"Sessie: {session.session.value} ({session.description})\n"
            f"Sentiment: {sentiment.get('label', 'n.v.t.')} ({sentiment.get('score', 0.0):+.2f})\n"
            f"Macro event: {sentiment.get('macro_event_level', 'LOW')}\n"
            f"Circuit Breaker: {cb_status} - {cb_description}\n"
            f"Risk multiplier: {cb.get('risk_multiplier', 1.0):.0%}\n"
            f"Signals enabled: {'yes' if control.get('signals_enabled', True) else 'no'}\n"
            f"Laatste bar: {runtime.get('last_bar', 'n.v.t.')}\n"
            f"Laatste training: {runtime.get('last_training_at', 'nog niet')}"
        )

    def run_forever(self) -> None:
        if not self.engine.connect():
            raise RuntimeError("Data/execution layer kon niet starten. Controleer MT5, CCXT of paper fallback.")

        self.telegram.start_in_background()
        self.telegram.notify(
            f"Autonomous XAUUSD systeem gestart in {self.settings.mode} mode voor "
            f"{self.settings.symbol} {self.settings.timeframe}."
        )

        try:
            while not self.stop_requested:
                self._process_control_commands()
                control = self.memory.get_bot_control_state()
                if not control.get("bot_active", True):
                    self._update_runtime_state(
                        status="stopped",
                        trading_paused=control.get("trading_paused", False),
                        emergency_stop=control.get("emergency_stop", False),
                        signals_enabled=control.get("signals_enabled", True),
                    )
                    time.sleep(self.settings.poll_interval_seconds)
                    continue

                self._run_cycle()
                time.sleep(self.settings.poll_interval_seconds)
        finally:
            self.engine.shutdown()
            self.memory.set_runtime_state(
                "engine_status",
                {
                    "status": "stopped",
                    "mode": self.settings.mode,
                    "symbol": self.settings.symbol,
                    "timeframe": self.settings.timeframe,
                    "stopped_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            # Herstart-verzoek via Telegram: exit code 1 zodat vps_startup.bat herstart
            if self._restart_requested:
                logger.info("Herstart gevraagd — exit code 1 (watchdog zal opnieuw starten)")
                sys.exit(1)

    def _run_cycle(self) -> None:
        try:
            control = self.memory.get_bot_control_state()
            if not control.get("bot_active", True):
                self._update_runtime_state(status="stopped")
                return
            if control.get("emergency_stop", False):
                self._update_runtime_state(
                    status="emergency_stop", trading_paused=True, emergency_stop=True,
                    signals_enabled=control.get("signals_enabled", True),
                )
                return
            if control.get("trading_paused", False):
                self._update_runtime_state(
                    status="paused", pause_reason="trading_paused", trading_paused=True,
                    signals_enabled=control.get("signals_enabled", True),
                )
                return

            session_info = self.session_engine.get_session_info()
            if not session_info.is_valid_for_trading:
                # Respect AUTO_TRADING_START/END_HOUR even outside premium sessions
                now_utc = datetime.now(timezone.utc)
                dow = now_utc.weekday()
                hour = now_utc.hour
                is_hard_block = (
                    dow >= 5  # Weekend
                    or (dow == 4 and hour >= self.settings.trading_end_hour)  # Vrijdag na einde
                )
                within_hours = self.settings.trading_start_hour <= hour < self.settings.trading_end_hour
                if is_hard_block or not within_hours:
                    logger.info("[WAIT: session_blocked] %s", session_info.description)
                    self._update_runtime_state(
                        status="waiting", session=session_info.session.value,
                        session_description=session_info.description,
                    )
                    return
                logger.debug(
                    "[SESSION: extended_hours] %s — doorgaan binnen geconfigureerde uren %d:00-%d:00 UTC",
                    session_info.description, self.settings.trading_start_hour, self.settings.trading_end_hour,
                )

            # ── Gedeelde checks (één keer per cycle) ──────────────
            account = self.engine.account_status()
            self.circuit_breaker.update_balance(
                balance=account.get("balance", 0.0),
                equity=account.get("equity", 0.0),
            )
            self.memory.save_circuit_breaker_state(self.circuit_breaker.get_persistent_state())
            self._ftmo_guard.update_equity(account.get("equity", 0.0))

            cb_status = self.circuit_breaker.get_status_summary()
            self.memory.set_runtime_state("circuit_breaker", cb_status)
            self.memory.set_runtime_state("ftmo_guard", self._ftmo_guard.get_status_dict())

            if not self.circuit_breaker.can_trade():
                reason = cb_status.get("circuit_description", "circuit breaker actief")
                logger.info("[WAIT: circuit_breaker] %s", reason)
                self._update_runtime_state(status="circuit_breaker", circuit_breaker_reason=reason,
                                           equity=account.get("equity", 0.0))
                return
            if not self._ftmo_guard.can_trade():
                locks = self._ftmo_guard.get_active_locks()
                blocking = [l for l in locks if l.locked and l.severity in ("BLOCK", "CRITICAL")]
                reason = blocking[0].reason if blocking else "FTMO protection active"
                logger.info("[WAIT: ftmo_blocked] %s", reason)
                self._update_runtime_state(status="ftmo_blocked", ftmo_reason=reason,
                                           equity=account.get("equity", 0.0))
                return

            news_decision = self._news_guard.check()
            self.memory.set_runtime_state("news_guard", news_decision.to_dict())
            if not news_decision.allow_trading:
                if news_decision.lock_expires_at:
                    self._ftmo_guard.set_news_lock(news_decision.lock_expires_at)
                logger.info("[WAIT: news_lock] %s", news_decision.reason)
                self._update_runtime_state(status="news_lock", news_reason=news_decision.reason,
                                           equity=account.get("equity", 0.0))
                return

            sentiment_result = self.sentiment.get_sentiment()
            self.memory.set_runtime_state("last_sentiment", sentiment_result.to_dict())
            current_sentiment = SentimentScore(
                score=sentiment_result.score, label=sentiment_result.label,
                headline_count=sentiment_result.headline_count,
                sources=sentiment_result.sources, fetched_at=sentiment_result.fetched_at,
            )

            _live_cfg = self.config_manager.get_strategy_cfg()
            max_concurrent = int(_live_cfg.get("max_concurrent_positions", 2)) if _live_cfg else 2

            # ── Per-paar loop ─────────────────────────────────────
            last_signal = None
            last_bar_any = None

            for sym in self.settings.symbols:
                try:
                    self._run_symbol_cycle(
                        sym, control, session_info, account, current_sentiment,
                        sentiment_result, cb_status, _live_cfg, max_concurrent,
                    )
                    last_signal = self.memory.get_runtime_state(f"last_signal_{sym}") or last_signal
                    last_bar_any = self.last_processed_bar.get(sym) or last_bar_any
                except Exception as sym_exc:
                    logger.warning("Fout bij cycle voor %s: %s", sym, sym_exc, exc_info=True)

            training = self._maybe_train()
            self._maybe_send_2h_report()
            self._maybe_send_daily_report()
            self._update_runtime_state(
                last_bar=last_bar_any or "",
                status="running",
                balance=account.get("balance", 0.0),
                equity=account.get("equity", 0.0),
                open_positions=account.get("open_positions", 0),
                last_signal=str(last_signal) if last_signal else "geen signaal",
                sentiment_label=current_sentiment.label,
                sentiment_score=current_sentiment.score,
                last_training_at=training.trained_at.isoformat() if training else None,
                session=session_info.session.value,
                circuit_breaker_active=cb_status.get("circuit_breaker_active", False),
                risk_multiplier=self.circuit_breaker.get_risk_multiplier(),
                trading_paused=control.get("trading_paused", False),
                emergency_stop=control.get("emergency_stop", False),
                signals_enabled=control.get("signals_enabled", True),
                symbols=list(self.settings.symbols),
            )
            self.consecutive_errors = 0

        except Exception as exc:
            self.consecutive_errors += 1
            logger.exception("Autonomous cycle mislukt")
            self._update_runtime_state(status="error", last_error=str(exc))
            if self.consecutive_errors >= self.settings.max_consecutive_errors:
                self.stop_requested = True
                self.telegram.notify(f"Engine gestopt na {self.consecutive_errors} opeenvolgende fouten: {exc}")

    def _sync_closed_trades(self, sym: str, open_trades: list, latest_bar) -> None:
        """Synchroniseer gesloten trades met broker en update alle lagen."""
        for closed_trade in self.engine.sync_trade_closures(open_trades, latest_bar=latest_bar):
            self.memory.log_trade_close(closed_trade)
            self.circuit_breaker.record_trade_result(closed_trade.pnl)
            self.memory.save_circuit_breaker_state(self.circuit_breaker.get_persistent_state())
            self._ftmo_guard.record_trade_closed(closed_trade.pnl)
            pattern_info = self._open_trade_patterns.pop(closed_trade.broker_ticket, None)
            if pattern_info is not None:
                pt_sig, pt_side, pt_regime, pt_session = pattern_info
                self._pattern_memory.record_trade_closed(
                    pt_sig, pt_side, closed_trade.pnl,
                    h4_regime=pt_regime, session=pt_session,
                )
            self.telegram.notify(self._format_trade_close_message(closed_trade))

    def _compute_drawdown_scale(self) -> float:
        """
        Schaalt risico omlaag naarmate drawdown de FTMO-limiet nadert.
          DD < 2%  → 1.00  (geen aanpassing)
          DD 2–4%  → 0.75
          DD 4–5%  → 0.50
          DD > 5%  → 0.30
        Gebaseerd op FTMO_START_CAPITAL; werkt onafhankelijk van circuit breaker.
        """
        try:
            ftmo = self._ftmo_guard.get_status_dict()
            total_dd = float(ftmo.get("total_drawdown", 0.0))
            start_cap = self.settings.ftmo_start_capital
            if start_cap <= 0:
                return 1.0
            dd_pct = total_dd / start_cap
            if dd_pct >= 0.05:
                return 0.30
            if dd_pct >= 0.04:
                return 0.50
            if dd_pct >= 0.02:
                return 0.75
            return 1.0
        except Exception:
            return 1.0

    def _open_trade(
        self,
        sym: str,
        signal,
        account: dict,
        current_sentiment,
        sentiment_result,
        session_info,
        sig_type: str,
        h4_regime: str,
        portfolio_scale: float = 1.0,
    ) -> None:
        """Voer een goedgekeurd signaal uit en log alle lagen."""
        risk_mult = self.circuit_breaker.get_risk_multiplier()
        kelly_mult = self._compute_kelly_multiplier(sig_type)
        dd_scale = self._compute_drawdown_scale()
        # Combineer: circuit breaker × Kelly × drawdown-scaling × portfolio (correlatie)
        # Kelly kan verhogen tot 1.3; dd_scale en portfolio_scale kunnen alleen verlagen.
        combined = risk_mult * kelly_mult * dd_scale * portfolio_scale
        final_risk_mult = round(float(np.clip(combined, 0.0, 1.3)), 3)
        logger.info(
            "Trade openen: %s %s %s | cb=%.0f%% kelly=%.0f%% dd=%.0f%% port=%.0f%% → final=%.0f%%",
            signal.side, sig_type, sym,
            risk_mult * 100, kelly_mult * 100, dd_scale * 100,
            portfolio_scale * 100, final_risk_mult * 100,
        )
        execution = self.engine.execute_trade(
            signal, self.parameters,
            account_equity=account.get("equity", 0.0),
            risk_multiplier=final_risk_mult,
        )
        self.memory.set_runtime_state(f"last_trade_opened_at_{sym}", datetime.now(timezone.utc).isoformat())
        self._ftmo_guard.record_trade_opened()
        self._pattern_memory.record_trade_opened(
            sig_type, signal.side, h4_regime=h4_regime, session=session_info.session.value,
        )
        self._open_trade_patterns[execution.broker_ticket] = (
            sig_type, signal.side, h4_regime, session_info.session.value,
        )
        self.memory.log_trade_open(execution, sentiment_score=current_sentiment.score)
        self.telegram.notify(
            self._format_trade_open_message(execution, signal, session_info, sentiment_result, final_risk_mult, sig_type)
        )

    def _log_no_signal_reason(self, sym: str, enriched, sym_cfg: dict | None) -> None:
        """Log een leesbare reden waarom er geen signaal gegenereerd werd."""
        try:
            bar = enriched.iloc[-2]
            h4reg = str(bar.get("h4_reg", "CHOPPY"))
            adx = float(bar.get("adx14", 0))
            h4adx = float(bar.get("h4_adx", 0))
            h4sl = float(bar.get("h4_sl", 0))
            rsi = float(bar.get("rsi14", 50))
            macdh = float(bar.get("macd_hist", 0))
            ema_xup = bool(bar.get("ema_xup", False))
            ema_xdn = bool(bar.get("ema_xdn", False))
            cfg_used = sym_cfg or {}
            adx_min = float(cfg_used.get("adx_min", 7))
            h4adx_min = float(cfg_used.get("h4adx_min", 10))

            if h4reg == "CHOPPY":
                reason = "H4 regime = CHOPPY (geen directional bias)"
            elif h4adx < h4adx_min:
                reason = f"H4 ADX {h4adx:.1f} < min {h4adx_min:.0f}"
            elif adx < adx_min * 0.75:
                reason = f"H1 ADX {adx:.1f} < min {adx_min * 0.75:.1f}"
            elif h4reg in ("STERK_BULL", "BULL", "ZWAK_BULL") and not ema_xup:
                reason = f"Bull regime maar geen EMA crossover — H4={h4reg} RSI={rsi:.0f} MACD={macdh:.2f}"
            elif h4reg in ("STERK_BEAR", "BEAR", "ZWAK_BEAR") and not ema_xdn:
                reason = f"Bear regime maar geen EMA crossdown — H4={h4reg} RSI={rsi:.0f} MACD={macdh:.2f}"
            else:
                reason = (
                    f"H4={h4reg} ADX={adx:.1f} H4ADX={h4adx:.1f} "
                    f"H4SL={h4sl:.2f} RSI={rsi:.0f} MACD={macdh:.2f}"
                )
            logger.info("[WAIT: no_signal] %s — %s", sym, reason)
        except Exception:
            logger.info("[WAIT: no_signal] %s — indicatoren konden niet worden geanalyseerd", sym)

    def _m15_confirms_signal(self, sym: str, side: str) -> bool:
        """
        Checkt of M15 EMA9 > EMA21 (long) of EMA9 < EMA21 (short) op de laatste gesloten bar.
        Bij data-fouten (MT5 niet beschikbaar, te weinig bars): altijd True (geen false negatives).
        """
        try:
            m15 = self.engine.fetch_candles_for_timeframe(sym, "M15", bars=30)
            if m15.empty or len(m15) < 22:
                return True
            close = m15["close"]
            ema9 = close.ewm(span=9, adjust=False).mean()
            ema21 = close.ewm(span=21, adjust=False).mean()
            last_ema9 = float(ema9.iloc[-2])
            last_ema21 = float(ema21.iloc[-2])
            if side == "buy":
                return last_ema9 > last_ema21
            return last_ema9 < last_ema21
        except Exception as exc:
            logger.debug("M15 bevestiging kon niet worden berekend voor %s: %s", sym, exc)
            return True

    def _run_symbol_cycle(
        self,
        sym: str,
        control: dict,
        session_info,
        account: dict,
        current_sentiment,
        sentiment_result,
        cb_status: dict,
        live_cfg: dict | None,
        max_concurrent: int,
    ) -> None:
        """Voert één trading cycle uit voor een enkel symbool."""
        market = self.engine.fetch_recent_candles(symbol=sym)
        enriched = self.brain.prepare_market_frame(market, self.parameters)
        if len(enriched) < 4:
            logger.debug("[WAIT: insufficient_bars] %s bars voor %s (min 4)", len(enriched), sym)
            return

        latest_closed_bar = enriched.index[-2].isoformat()
        latest_bar = enriched.iloc[-2]
        if latest_closed_bar == self.last_processed_bar.get(sym):
            return
        self.last_processed_bar[sym] = latest_closed_bar

        open_trades = self.memory.list_open_trades(sym)
        self._sync_closed_trades(sym, open_trades, latest_bar)

        total_open = sum(len(self.memory.list_open_trades(s)) for s in self.settings.symbols)
        if total_open >= max_concurrent:
            logger.info("[WAIT: max_concurrent_positions] %d/%d posities open (%s)", total_open, max_concurrent, sym)
            return

        if self.engine.has_open_position(sym):
            logger.debug("[WAIT: position_open] open positie aanwezig voor %s — geen nieuw signaal", sym)
            return

        if not control.get("signals_enabled", True):
            logger.info("[WAIT: signals_disabled] signalen uitgeschakeld via control")
            return

        sym_cfg = get_symbol_cfg(live_cfg, sym) if live_cfg else None
        signal = self.brain.generate_signal(
            enriched,
            self.parameters,
            sym,
            self.settings.timeframe,
            sentiment=current_sentiment,
            sentiment_threshold=self.settings.sentiment_filter_threshold,
            is_killzone=session_info.is_killzone,
            strategy_cfg=sym_cfg,
        )

        if not signal:
            self._log_no_signal_reason(sym, enriched, sym_cfg)
            return

        self._record_signal(signal)
        self.memory.set_runtime_state(f"last_signal_{sym}", signal.reason)
        self.telegram.notify(self._format_signal_detected_message(signal, session_info, sentiment_result))

        sig_type = (
            signal.features.get("signal_type", signal.reason)
            if isinstance(signal.features, dict) else signal.reason
        )
        h4_regime = signal.market_regime or ""

        if not self.circuit_breaker.is_signal_allowed(sig_type):
            logger.info("[WAIT: circuit_breaker_signal] %s %s geblokkeerd", sym, sig_type)
            return
        if self._pattern_memory.is_blocked(sig_type, signal.side, h4_regime=h4_regime):
            logger.info(
                "[WAIT: pattern_memory_blocked] %s %s %s geblokkeerd door verlieshistorie",
                sym, sig_type, signal.side,
            )
            return

        # M15 entry-bevestiging: EMA9 vs EMA21 op M15 moet richting bevestigen.
        # Vermindert SL-afstand door alleen entries te nemen met momentum-alignment op lagere TF.
        if not self._m15_confirms_signal(sym, signal.side):
            logger.info(
                "[WAIT: m15_no_confirm] %s %s — M15 EMA niet aligned met %s richting",
                sym, sig_type, signal.side,
            )
            return

        # Correlation filter: EURUSD en GBPUSD zijn sterk gecorreleerde USD-pairs (~85%).
        # Als er al een gecorreleerde positie in dezelfde richting open is:
        #   - 1 gecorreleerde positie → risico halveren (0.5×) i.p.v. blokkeren
        #   - ≥ max_correlated_positions+1 → volledig blokkeren
        portfolio_scale = 1.0
        if sym in _CORRELATED_GROUP and self.settings.max_correlated_positions > 0:
            same_dir_count = sum(
                1
                for other_sym in _CORRELATED_GROUP
                if other_sym != sym
                for trade in self.memory.list_open_trades(other_sym)
                if trade.get("side") == signal.side
            )
            if same_dir_count >= self.settings.max_correlated_positions + 1:
                logger.info(
                    "[WAIT: correlation_filter] %s %s geblokkeerd — %d gecorreleerde %s positie(s) al open",
                    sym, signal.side, same_dir_count, signal.side,
                )
                return
            if same_dir_count >= self.settings.max_correlated_positions:
                portfolio_scale = 0.5
                logger.info(
                    "[CORR: risk_halved] %s %s — gecorreleerde positie open, risico gehalveerd (0.5×)",
                    sym, signal.side,
                )

        allowed, gate_reason = self._can_open_trade(account, sym)
        if not allowed:
            logger.info("[WAIT: risk_gate] %s — %s %s %s", gate_reason, signal.side, sig_type, sym)
            return

        self._open_trade(
            sym, signal, account, current_sentiment, sentiment_result,
            session_info, sig_type, h4_regime, portfolio_scale=portfolio_scale,
        )

    def _run_training_cycle(self) -> TrainingOutcome | None:
        trade_frame = self.memory.fetch_training_frame()
        outcome = self.brain.train_model(trade_frame, self.parameters)
        if outcome is None:
            return None

        self.memory.save_model_snapshot(outcome)
        if outcome.parameter_overrides:
            self.parameters = self.parameters.with_overrides(outcome.parameter_overrides)
            self.memory.save_strategy_parameters(self.parameters, source="ml_feedback_loop")

        history = self.memory.fetch_analytics_frame()
        ml_hist = self.memory.model_history()
        report = compute_report(history, ml_hist)
        self.memory.set_runtime_state("analytics_report", report.to_dict())
        self.memory.set_runtime_state(
            "last_training",
            {
                "trained_at": outcome.trained_at.isoformat(),
                "sample_count": outcome.sample_count,
                "accuracy": outcome.accuracy,
                "overrides": outcome.parameter_overrides,
                "analytics": {
                    "win_rate": report.win_rate,
                    "profit_factor": report.profit_factor,
                    "max_drawdown": report.max_drawdown,
                },
            },
        )
        self.telegram.notify(
            f"ML training voltooid. Accuracy={outcome.accuracy:.2%}, F1={outcome.f1_score:.2%}\n"
            f"Analytics: WR={report.win_rate:.2%} PF={report.profit_factor:.2f} MaxDD={report.max_drawdown:.2f}"
        )
        return outcome

    def _maybe_train(self) -> TrainingOutcome | None:
        last_training = self.memory.get_runtime_state("last_training")
        if last_training:
            trained_at = datetime.fromisoformat(last_training["trained_at"])
            if datetime.now(timezone.utc) - trained_at < timedelta(days=self.settings.train_every_days):
                return None
        return self._run_training_cycle()

    # ──────────────────────────────────────────────────────────────
    # 2-UURS TELEGRAM RAPPORT  (production heartbeat naar eigenaar)
    # ──────────────────────────────────────────────────────────────

    _REPORT_INTERVAL_SECONDS: int = 7200  # 2 uur

    def _maybe_send_2h_report(self) -> None:
        """Verstuurt elke 2 uur een kort statusrapport naar Telegram."""
        now = datetime.now(timezone.utc)
        state_key = "two_hour_report"
        last = self.memory.get_runtime_state(state_key) or {}
        last_ts_str = last.get("sent_at")

        if last_ts_str:
            try:
                last_ts = datetime.fromisoformat(last_ts_str)
                elapsed = (now - last_ts).total_seconds()
                if elapsed < self._REPORT_INTERVAL_SECONDS:
                    return
            except Exception:
                pass

        logger.info("[REPORT_JOB_STARTED] 2-uurs Telegram rapport genereren")
        try:
            msg = self._build_2h_report(now)
            logger.info("[REPORT_GENERATED] 2-uurs rapport gegenereerd (%d chars)", len(msg))
            sent = self.telegram.notify(msg)
            if sent:
                logger.info("[REPORT_SENT_SUCCESS] 2-uurs rapport verstuurd naar Telegram")
                self.memory.set_runtime_state(state_key, {
                    "sent_at": now.isoformat(),
                    "next_report_at": (
                        now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=2)
                    ).isoformat(),
                })
            else:
                logger.warning("[REPORT_SEND_FAILED] Telegram kon rapport niet versturen")
            next_ts = now.timestamp() + self._REPORT_INTERVAL_SECONDS
            logger.info(
                "[NEXT_REPORT_TIME] Volgend rapport om %s UTC",
                datetime.fromtimestamp(next_ts, tz=timezone.utc).strftime("%H:%M"),
            )
        except Exception as exc:
            logger.warning("[REPORT_SEND_FAILED] 2-uurs rapport fout: %s", exc)

    def _build_2h_report(self, now: datetime) -> str:
        runtime = self.memory.get_runtime_state("engine_status") or {}
        cb = self.circuit_breaker.get_status_summary()
        ftmo = self._ftmo_guard.get_status_dict()
        session = self.session_engine.get_session_info()
        control = self.memory.get_bot_control_state()
        sentiment = self.memory.get_runtime_state("last_sentiment") or {}
        news = self.memory.get_runtime_state("news_guard") or {}

        equity = float(runtime.get("equity", 0.0))
        balance = float(runtime.get("balance", 0.0))
        open_pos = int(runtime.get("open_positions", 0))
        status = str(runtime.get("status", "onbekend"))
        last_bar = str(runtime.get("last_bar", "n.v.t."))

        today = now.date()
        daily = self.memory.daily_summary(today)
        trades_today = int(daily.get("trade_count", 0))
        pnl_today = float(daily.get("realized_pnl", 0.0))
        wins = int(daily.get("trade_count", 0)) - int(daily.get("loss_count", 0))
        losses = int(daily.get("loss_count", 0))

        cb_active = cb.get("circuit_breaker_active", False)
        ftmo_ok = not cb_active and self._ftmo_guard.can_trade()
        daily_remaining = ftmo.get("daily_remaining", ftmo.get("daily_loss_limit", 6000))

        last_signal_state = self.memory.get_runtime_state("last_signal") or {}
        last_signal_time = last_signal_state.get("time", "nog geen signaal")

        lines = [
            f"📊 2-UURS RAPPORT — {now.strftime('%d %b %H:%M')} UTC",
            "━━━━━━━━━━━━━━━━━━━━━━━━",
            f"Status: {'🟢 actief' if status == 'running' else '🟡 ' + status}",
            f"Modus: {self.settings.mode.upper()} | {self.settings.symbol}",
            "",
            "ACCOUNT",
            f"  Equity:  €{equity:,.2f}",
            f"  Balance: €{balance:,.2f}",
            f"  Open:    {open_pos} positie(s)",
            "",
            f"VANDAAG ({today.strftime('%d %b')})",
            f"  Trades: {trades_today}  (✅{wins}W / ❌{losses}L)",
            f"  PnL:    €{pnl_today:+,.2f}",
            f"  FTMO ruimte: €{daily_remaining:,.0f} resterend",
            "",
            "SIGNALEN",
            f"  Laatste signaal: {last_signal_time}",
            f"  Sessie: {session.session.value.upper()} — {'VALID' if session.is_valid_for_trading else 'GEBLOKKEERD'}",
            f"  Sentiment: {sentiment.get('label', 'n.v.t.')} ({float(sentiment.get('score', 0)):+.2f})",
            f"  Nieuws lock: {'JA — ' + news.get('reason', '') if not news.get('allow_trading', True) else 'nee'}",
            "",
            "SYSTEEM",
            f"  Circuit breaker: {'🔴 ACTIEF' if cb_active else '🟢 OK'}",
            f"  FTMO bescherming: {'✅ OK' if ftmo_ok else '⚠️ ACTIEF'}",
            f"  Signals enabled: {'ja' if control.get('signals_enabled', True) else 'NEE'}",
            f"  Laatste bar: {last_bar}",
            "━━━━━━━━━━━━━━━━━━━━━━━━",
        ]
        return "\n".join(lines)

    def _maybe_send_daily_report(self) -> None:
        report_state = self.memory.get_runtime_state("daily_report")
        now = datetime.now(timezone.utc)
        if now.hour < self.settings.daily_report_hour_utc:
            return
        if report_state and report_state.get("day") == now.date().isoformat():
            return

        self.telegram.notify(self._build_daily_report(now))
        self.memory.set_runtime_state("daily_report", {"day": now.date().isoformat(), "sent_at": now.isoformat()})

    def _build_daily_report(self, now: datetime) -> str:
        today = now.date()
        summary = self.memory.daily_summary(today)
        sentiment = self.memory.get_runtime_state("last_sentiment") or {}
        cb = self.circuit_breaker.get_status_summary()
        ftmo = self._ftmo_guard.get_status_dict()
        training = self.memory.get_runtime_state("last_training") or {}
        engine = self.memory.get_runtime_state("engine_status") or {}

        trade_count = int(summary.get("trade_count", 0))
        realized_pnl = float(summary.get("realized_pnl", 0.0))
        win_rate = float(summary.get("win_rate", 0.0))
        loss_count = int(summary.get("loss_count", 0))
        win_count = trade_count - loss_count

        # Best/worst trade via trade history
        best_pnl = worst_pnl = best_type = worst_type = None
        sig_type_stats: list[str] = []
        try:
            history = self.memory.trade_history(limit=500)
            if not history.empty and "closed_at" in history.columns:
                history["closed_day"] = pd.to_datetime(history["closed_at"]).dt.date
                day_trades = history[history["closed_day"] == today]
                if not day_trades.empty and "pnl" in day_trades.columns:
                    pnls = day_trades["pnl"].fillna(0.0)
                    best_idx = pnls.idxmax()
                    worst_idx = pnls.idxmin()
                    best_pnl = float(pnls[best_idx])
                    worst_pnl = float(pnls[worst_idx])
                    if "signal_type" in day_trades.columns:
                        best_type = day_trades.loc[best_idx, "signal_type"]
                        worst_type = day_trades.loc[worst_idx, "signal_type"]
                        # Per-signaaltype stats voor vandaag
                        for stype, grp in day_trades.groupby("signal_type"):
                            st_pnls = grp["pnl"].fillna(0.0)
                            st_wins = int((st_pnls > 0).sum())
                            st_total = len(st_pnls)
                            st_pnl = float(st_pnls.sum())
                            wr_st = st_wins / st_total if st_total > 0 else 0.0
                            emoji = "✅" if st_pnl >= 0 else "❌"
                            sig_type_stats.append(
                                f"  {str(stype):<14} {st_total}T  {wr_st:.0%}WR  {emoji}€{st_pnl:+,.0f}"
                            )
        except Exception:
            pass

        # Signals today from signal_history in bot_state
        signals_today = 0
        try:
            state = {}
            if _BOT_STATE_PATH.exists():
                state = json.loads(_BOT_STATE_PATH.read_text(encoding="utf-8"))
            for item in state.get("signal_history", []):
                if str(item.get("time", "")).startswith(today.isoformat()):
                    signals_today += 1
        except Exception:
            pass

        pnl_emoji = "🟢" if realized_pnl >= 0 else "🔴"
        daily_remaining = ftmo.get("daily_remaining", ftmo.get("daily_loss_limit", 6000))
        total_dd = float(ftmo.get("total_drawdown", 0))
        equity = float(engine.get("equity", 0.0))
        balance = float(engine.get("balance", 0.0))

        lines = [
            f"📋 DAGRAPPORT — {today.strftime('%d %b %Y')}",
            "━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            "TRADING RESULTAAT",
            f"  {pnl_emoji} Totaal PnL:   €{realized_pnl:+,.2f}",
            f"  Trades:       {trade_count}  (✅ {win_count}W / ❌ {loss_count}L)",
            f"  Win rate:     {win_rate:.1%}",
        ]

        if signals_today > 0:
            executed = trade_count
            lines.append(f"  Signalen:     {signals_today} gedetecteerd → {executed} uitgevoerd")

        if sig_type_stats:
            lines.append("")
            lines.append("PER SIGNAALTYPE (vandaag)")
            lines.extend(sig_type_stats)

        if best_pnl is not None and trade_count > 0:
            lines.append("")
            lines.append("BESTE / SLECHTSTE TRADE")
            best_label = f"  ({best_type})" if best_type else ""
            worst_label = f"  ({worst_type})" if worst_type else ""
            lines.append(f"  Beste:  €{best_pnl:+,.2f}{best_label}")
            lines.append(f"  Slechtste: €{worst_pnl:+,.2f}{worst_label}")

        lines += [
            "",
            "ACCOUNT",
            f"  Equity:  €{equity:,.2f}",
            f"  Balance: €{balance:,.2f}",
            "",
            "FTMO BESCHERMING",
            f"  Dag ruimte:   €{daily_remaining:,.0f} resterend",
            f"  Totaal DD:    €{total_dd:,.0f}",
            f"  Status:       {'✅ COMPLIANT' if cb.get('ftmo_compliant', True) else '⚠️ KRITIEK'}",
            "",
            "SYSTEEM",
            f"  Circuit breaker: {'🔴 ACTIEF' if cb.get('circuit_breaker_active') else '🟢 OK'}",
            f"  Risk multiplier: {cb.get('risk_multiplier', 1.0):.0%}",
            f"  Sentiment:       {sentiment.get('label', 'n.v.t.')} ({float(sentiment.get('score', 0.0)):+.2f})",
        ]

        if training:
            acc = float(training.get("accuracy", 0.0))
            lines.append(f"  ML accuracy:     {acc:.1%}")

        lines += ["", "━━━━━━━━━━━━━━━━━━━━━━━━"]
        return "\n".join(lines)

    def _update_runtime_state(self, **payload: object) -> None:
        current = self.memory.get_runtime_state("engine_status") or {}
        merged = {
            **current,
            **payload,
            "mode": self.settings.mode,
            "symbol": self.settings.symbol,
            "timeframe": self.settings.timeframe,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.memory.set_runtime_state("engine_status", merged)

    def _process_control_commands(self) -> None:
        commands = self.memory.fetch_pending_control_commands(limit=20)
        for command in commands:
            command_id: int | None = None
            try:
                command_id = int(command["id"])
                action_raw = command.get("command")
                if not isinstance(action_raw, str) or not action_raw.strip():
                    raise ValueError("Missing control command action")
                action = action_raw.strip()
            except (ValueError, TypeError):
                logger.error("Malformed control command skipped: %s", command)
                if command_id is not None:
                    self.memory.update_control_command(
                        command_id,
                        "failed",
                        error_message="Malformed control command payload.",
                    )
                continue
            try:
                result = self._execute_control_command(action)
                self.memory.update_control_command(command_id, "completed", result_message=result)
                self.telegram.notify(result)
            except Exception as exc:
                logger.exception("Control command failed: %s", action)
                self.memory.update_control_command(command_id, "failed", error_message=str(exc))
                self.telegram.notify(f"Control command mislukt ({action}): {exc}")

    def _execute_control_command(self, action: str) -> str:
        if action == "start_bot":
            self.memory.set_bot_control_state(bot_active=True, trading_paused=False, emergency_stop=False)
            return "Bot gestart. Trading-cycli worden hervat."
        if action == "stop_bot":
            self.memory.set_bot_control_state(bot_active=False)
            return "Bot gestopt. Monitoring blijft beschikbaar via Telegram."
        if action == "pause_trading":
            self.memory.set_bot_control_state(trading_paused=True)
            return "Trading gepauzeerd. Open posities blijven beheerd."
        if action == "resume_trading":
            current = self.memory.get_bot_control_state()
            if current.get("emergency_stop", False):
                return "Resume geweigerd: emergency stop is actief. Gebruik 'Start Bot' om de emergency stop te wissen."
            self.memory.set_bot_control_state(bot_active=True, trading_paused=False)
            return "Trading hervat."
        if action == "emergency_stop":
            self.memory.set_bot_control_state(bot_active=False, trading_paused=True, emergency_stop=True)
            return "Emergency stop bevestigd. Nieuwe trades zijn uitgeschakeld."
        if action == "close_all_positions":
            closed = []
            for sym in self.settings.symbols:
                closed.extend(self.engine.close_all_positions(symbol=sym, reason="telegram_close_all"))
            for trade in closed:
                self.memory.log_trade_close(trade)
                self.circuit_breaker.record_trade_result(trade.pnl)
                self._ftmo_guard.record_trade_closed(trade.pnl)
                pattern_info = self._open_trade_patterns.pop(trade.broker_ticket, None)
                if pattern_info is not None:
                    pt_sig, pt_side, pt_regime, pt_session = pattern_info
                    self._pattern_memory.record_trade_closed(
                        pt_sig, pt_side, trade.pnl, h4_regime=pt_regime, session=pt_session,
                    )
            return f"Alle posities gesloten: {len(closed)}."
        if action == "train_ai":
            outcome = self._run_training_cycle()
            if outcome is None:
                return "AI training overgeslagen: onvoldoende gesloten trades."
            return f"AI training voltooid. Accuracy={outcome.accuracy:.2%}, samples={outcome.sample_count}."
        raise ValueError(f"Unsupported control command: {action}")

    # ──────────────────────────────────────────────────────────────
    # PRE-TRADE RISK GATES
    # ──────────────────────────────────────────────────────────────

    def _compute_kelly_multiplier(self, sig_type: str) -> float:
        """
        Berekent een risico-multiplier op basis van quarter-Kelly formule.
        Gebruikt historische trades om win rate en gem. R:R te berekenen.
        Retourneert een multiplier in [0.5, 1.3] — schaalt bestaande risk_pct.

        Kelly formula: f* = (p × b - q) / b
          p = win rate, q = 1-p, b = gem_win / gem_verlies (R:R verhouding)
        Quarter-Kelly: f = f* × kelly_fraction
        """
        if self.settings.kelly_fraction <= 0:
            return 1.0
        try:
            history = self.memory.trade_history(limit=self.settings.kelly_lookback_trades * 2)
            if history.empty or len(history) < 20:
                return 1.0
            closed = history[history["pnl"].notna()] if "pnl" in history.columns else history
            if "signal_type" in closed.columns and sig_type:
                sig_history = closed[closed["signal_type"] == sig_type]
                if len(sig_history) >= 15:
                    closed = sig_history
            pnls = closed["pnl"].dropna() if "pnl" in closed.columns else pd.Series(dtype=float)
            if len(pnls) < 15:
                return 1.0
            wins = pnls[pnls > 0]
            losses = pnls[pnls <= 0]
            if len(losses) == 0 or len(wins) == 0:
                return 1.0
            win_rate = len(wins) / len(pnls)
            avg_rr = float(wins.mean()) / float(abs(losses.mean()))
            if avg_rr <= 0:
                return 1.0
            q = 1.0 - win_rate
            kelly_full = (win_rate * avg_rr - q) / avg_rr
            kelly_full = max(0.0, min(kelly_full, 1.0))
            # Normaliseer: quarter-Kelly van 0.25 (kelly=1.0) = multiplier 1.0
            scaled = (kelly_full * self.settings.kelly_fraction) / 0.25
            result = round(float(np.clip(scaled, 0.5, 1.3)), 2)
            logger.debug(
                "Kelly[%s]: WR=%.1f%% RR=%.2f kelly=%.3f fraction=%.2f → mult=%.2f",
                sig_type, win_rate * 100, avg_rr, kelly_full, self.settings.kelly_fraction, result,
            )
            return result
        except Exception as exc:
            logger.debug("Kelly multiplier berekening mislukt: %s", exc)
            return 1.0

    def _compute_portfolio_heat(self, equity: float) -> float:
        """
        Berekent totaal open risico als fractie van equity.
        Formule: som van (SL-afstand × volume × lot_factor) voor alle open posities.
        Als alle SL's tegelijk geraakt worden, verlies je heat% van equity.
        """
        if equity <= 0:
            return 0.0
        total_risk = 0.0
        for sym in self.settings.symbols:
            lot_factor = float(SYMBOL_SPECS.get(sym, {}).get("lot_factor", 100))
            for trade in self.memory.list_open_trades(sym):
                sl_dist = abs(float(trade.get("entry_price", 0)) - float(trade.get("stop_loss", 0)))
                volume = float(trade.get("volume", 0))
                total_risk += sl_dist * volume * lot_factor
        return total_risk / equity

    def _can_open_trade(self, account: dict, sym: str) -> tuple[bool, str]:
        """
        Hard risk gates evaluated before every execute_trade() call.
        Returns (allowed, reason).  All decisions are logged so the
        decision trail is always auditable.
        """
        now = datetime.now(timezone.utc)
        today = now.date()

        orphaned = self.memory.get_runtime_state(f"orphaned_positions_{sym}") or {}
        orphaned_count = int(orphaned.get("count", 0) or 0)
        if orphaned_count > 0:
            return False, f"orphaned_positions_detected={orphaned_count}"

        # Gate 1: max open positions (global, across all symbols)
        open_trades = self.memory.list_open_trades(sym)
        if len(open_trades) >= self.settings.max_open_positions:
            return False, f"max_open_positions={self.settings.max_open_positions} bereikt ({len(open_trades)} open)"

        # Gate 2: max trades per day (opened today — closed + still open)
        daily = self.memory.daily_summary(today)
        closed_today = int(daily.get("trade_count", 0))
        open_today = 0
        for trade in open_trades:
            opened_at = trade.get("opened_at")
            if hasattr(opened_at, "date") and opened_at.date() == today:
                open_today += 1
        opened_today = closed_today + open_today
        if opened_today >= self.settings.max_trades_per_day:
            return False, f"max_trades_per_day={self.settings.max_trades_per_day} bereikt ({opened_today} vandaag)"

        # Gate 3: max losses per day  (approx from win-rate on closed trades)
        losses_today = int(daily.get("loss_count", 0))
        if losses_today >= self.settings.max_losses_per_day:
            return (
                False,
                f"max_losses_per_day={self.settings.max_losses_per_day} bereikt ({losses_today} verlies vandaag)",
            )

        # Gate 4: cooldown between trades (per-symbool zodat EUR/GBP onafhankelijk traden)
        last_opened = self.memory.get_runtime_state(f"last_trade_opened_at_{sym}")
        if last_opened:
            try:
                elapsed_min = (now - datetime.fromisoformat(last_opened)).total_seconds() / 60
                if elapsed_min < self.settings.signal_cooldown_minutes:
                    return (
                        False,
                        f"cooldown actief: {elapsed_min:.0f}/{self.settings.signal_cooldown_minutes} min",
                    )
            except Exception:
                pass

        # Gate 5: broker connection — reject if account data unavailable
        if not account.get("equity") and not account.get("balance"):
            return False, "broker_data_unavailable (equity=0, balance=0)"

        # Gate 6: portfolio heat — totaal open risico mag max_portfolio_heat% van equity niet overschrijden
        equity = float(account.get("equity", 0.0))
        if equity > 0 and self.settings.max_portfolio_heat > 0:
            heat = self._compute_portfolio_heat(equity)
            if heat > self.settings.max_portfolio_heat:
                return (
                    False,
                    f"portfolio_heat={heat:.1%} > max={self.settings.max_portfolio_heat:.1%} "
                    f"(totaal open risico te hoog)",
                )

        return True, "alle_gates_ok"

    def _format_signal_detected_message(self, signal, session_info, sentiment_result) -> str:
        direction_emoji = "📈" if signal.side == "buy" else "📉"
        features = signal.features if isinstance(signal.features, dict) else {}
        sig_type = features.get("signal_type", signal.reason)
        confidence = features.get("confidence", features.get("ml_confidence", 0.0))
        sl_pts = abs(signal.entry_price - signal.stop_loss)
        tp_pts = abs(signal.take_profit - signal.entry_price)
        rr = tp_pts / sl_pts if sl_pts > 0 else 0.0
        lines = [
            f"{direction_emoji} SIGNAAL GEDETECTEERD — {signal.symbol}",
            "",
            f"Type:       {sig_type}",
            f"Richting:   {'LONG' if signal.side == 'buy' else 'SHORT'}",
            f"Entry:      {signal.entry_price:.2f}",
            f"Stop Loss:  {signal.stop_loss:.2f}  ({sl_pts:.1f} pts)",
            f"Take Profit:{signal.take_profit:.2f}  ({tp_pts:.1f} pts)",
            f"R:R ratio:  1:{rr:.1f}",
        ]
        if confidence:
            lines.append(f"ML conf:    {float(confidence):.1%}")
        lines += [
            "",
            f"Sessie:     {session_info.session.value.upper()}",
            f"Regime:     {signal.market_regime or 'unknown'}",
            f"Sentiment:  {sentiment_result.label} ({sentiment_result.score:+.2f})",
            "",
            "Trade volgt als alle risk-gates OK zijn.",
        ]
        return "\n".join(lines)

    def _format_trade_open_message(
        self, execution, signal, session_info, sentiment_result, risk_mult: float, sig_type: str
    ) -> str:
        direction_emoji = "🟢 LONG" if execution.side.lower() == "buy" else "🔴 SHORT"
        sl_pts = abs(execution.entry_price - execution.stop_loss)
        tp_pts = abs(execution.take_profit - execution.entry_price)
        rr = tp_pts / sl_pts if sl_pts > 0 else 0.0
        regime = execution.market_regime or "unknown"
        features = execution.features if isinstance(execution.features, dict) else {}
        confidence = features.get("confidence", features.get("ml_confidence", 0.0))
        pat_mult = self._pattern_memory.get_risk_multiplier(
            sig_type,
            execution.side,
            h4_regime=regime,
            session=session_info.session.value,
        )
        ftmo = self._ftmo_guard.get_status_dict()
        daily_remaining = ftmo.get("daily_remaining", ftmo.get("daily_loss_limit", 6000))
        total_remaining = ftmo.get("total_dd_limit", 16000) - ftmo.get("total_drawdown", 0)

        lines = [
            f"{direction_emoji} TRADE GEOPEND — {execution.symbol}",
            "",
            f"Signaal:    {sig_type}",
            f"Entry:      {execution.entry_price:.2f}",
            f"Stop Loss:  {execution.stop_loss:.2f}  ({sl_pts:.1f} pts)",
            f"Take Profit:{execution.take_profit:.2f}  ({tp_pts:.1f} pts)",
            f"R:R ratio:  1:{rr:.1f}",
            f"Lot size:   {execution.volume:.2f}",
            "",
            f"Sessie:     {session_info.session.value.upper()}",
            f"Regime:     {regime}",
            f"Sentiment:  {sentiment_result.label} ({sentiment_result.score:+.2f})",
        ]
        if confidence:
            lines.append(f"ML conf:    {float(confidence):.1%}")
        fvg_tag = "FVG" if features.get("fvg_confirms") else ""
        sweep_tag = "SWEEP" if features.get("sweep_confirms") else ""
        quality_tags = " ".join(filter(None, [fvg_tag, sweep_tag]))
        if quality_tags:
            lines.append(f"Kwaliteit:  {quality_tags}")
        lines += [
            f"Risk mult:  CB+Kelly={risk_mult:.0%}  PAT={pat_mult:.0%}",
            "",
            "FTMO ruimte:",
            f"  Dag:      €{daily_remaining:,.0f} resterend",
            f"  Totaal:   €{total_remaining:,.0f} resterend",
            "",
            f"Mode: {execution.mode.upper()}  |  Ticket: {execution.broker_ticket}",
        ]
        return "\n".join(lines)

    def _format_trade_close_message(self, closed_trade) -> str:
        won = closed_trade.pnl >= 0
        result_emoji = "✅ WIN" if won else "❌ VERLIES"
        reason_map = {
            "tp": "TP geraakt",
            "sl": "SL geraakt",
            "manual": "Manueel",
            "telegram_close_all": "Emergency close",
        }
        reason_label = reason_map.get(closed_trade.close_reason.lower(), closed_trade.close_reason)
        ftmo = self._ftmo_guard.get_status_dict()
        daily_used = ftmo.get("daily_loss_used", 0)
        daily_limit = ftmo.get("daily_loss_limit", 6000)
        total_dd = ftmo.get("total_drawdown", 0)
        daily_pct = (daily_used / daily_limit * 100) if daily_limit else 0

        lines = [
            f"{result_emoji} — {closed_trade.symbol} trade gesloten",
            "",
            f"Exit:       {closed_trade.exit_price:.2f}",
            f"PnL:        €{closed_trade.pnl:+,.2f}",
            f"Reden:      {reason_label}",
            "",
            "FTMO na trade:",
            f"  Dag verlies:  €{daily_used:,.0f} / €{daily_limit:,.0f}  ({daily_pct:.1f}%)",
            f"  Totaal DD:    €{total_dd:,.0f}",
        ]
        return "\n".join(lines)

    def _record_signal(self, signal) -> None:
        payload = {
            "symbol": signal.symbol,
            "timeframe": signal.timeframe,
            "side": signal.side,
            "reason": signal.reason,
            "confidence": float(signal.features.get("confidence", 0.0)) if isinstance(signal.features, dict) else 0.0,
            "time": signal.opened_at.isoformat(),
        }
        self.memory.set_runtime_state("last_signal", payload)
        try:
            state = {}
            if _BOT_STATE_PATH.exists():
                state = json.loads(_BOT_STATE_PATH.read_text(encoding="utf-8"))
            history = state.get("signal_history", [])
            if not isinstance(history, list):
                history = []
            history.append(payload)
            state["last_signal"] = payload
            state["signal_history"] = history[-100:]
            _BOT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            _tmp = _BOT_STATE_PATH.with_suffix(".tmp")
            _tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
            _tmp.replace(_BOT_STATE_PATH)
        except Exception as exc:
            logger.debug("Signal history write failed: %s", exc)


def main() -> None:
    AutonomousTradingSystem().run_forever()
