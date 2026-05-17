from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.circuit_breaker_singleton import get_circuit_breaker
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
        self.memory.set_bot_control_state(
            bot_active=True,
            trading_paused=False,
            signals_enabled=True,
            emergency_stop=False,
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
                start_capital=160_000.0,
                max_daily_loss=6_000.0,       # was €8,000 — verlaagd voor extra bescherming
                max_weekly_loss=10_000.0,     # was €11,200 — proportioneel aangepast
                max_total_drawdown=16_000.0,
                daily_buffer=400.0,           # stop bij €5,600 dagverlies
            )
        )

        self.stop_requested = False
        self.consecutive_errors = 0
        self.last_processed_bar: str | None = None

        self.telegram = TelegramControlLayer(
            token=self.settings.telegram_bot_token,
            chat_id=self.settings.telegram_chat_id,
            owner_user_id=self.settings.telegram_owner_user_id,
            backend_api_key=self.settings.telegram_control_api_key,
            backend_base_url=self.settings.telegram_backend_base_url,
            status_callback=self._status_text,
            stop_callback=self.request_stop,
            train_callback=self.train_now,
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

    def _status_text(self) -> str:
        runtime = self.memory.get_runtime_state("engine_status") or {}
        sentiment = self.memory.get_runtime_state("last_sentiment") or {}
        cb = self.circuit_breaker.get_status_summary()
        session = self.session_engine.get_session_info()
        control = self.memory.get_bot_control_state()
        return (
            f"V20 Status: {runtime.get('status', 'idle')}\n"
            f"Mode: {runtime.get('mode', self.settings.mode)}\n"
            f"Symbool: {runtime.get('symbol', self.settings.symbol)} {runtime.get('timeframe', self.settings.timeframe)}\n"
            f"Open posities: {runtime.get('open_positions', 0)}\n"
            f"Equity: EUR {runtime.get('equity', 0.0):,.2f}\n"
            f"Sessie: {session.session.value} ({session.description})\n"
            f"Sentiment: {sentiment.get('label', 'n.v.t.')} ({sentiment.get('score', 0.0):+.2f})\n"
            f"Macro event: {sentiment.get('macro_event_level', 'LOW')}\n"
            f"Circuit Breaker: {'ACTIVE' if cb.get('circuit_breaker_active') else 'OK'} - {cb.get('circuit_description', '')}\n"
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

    def _run_cycle(self) -> None:
        try:
            control = self.memory.get_bot_control_state()
            session_info = self.session_engine.get_session_info()
            if not session_info.is_valid_for_trading:
                self._update_runtime_state(
                    status="waiting",
                    session=session_info.session.value,
                    session_description=session_info.description,
                )
                return

            market = self.engine.fetch_recent_candles()
            enriched = self.brain.prepare_market_frame(market, self.parameters)
            if len(enriched) < 4:
                return

            latest_closed_bar = enriched.index[-2].isoformat()
            latest_bar = enriched.iloc[-2]
            if latest_closed_bar == self.last_processed_bar:
                self._update_runtime_state(last_bar=latest_closed_bar, status="waiting")
                return

            self.last_processed_bar = latest_closed_bar
            open_trades = self.memory.list_open_trades(self.settings.symbol)
            for closed_trade in self.engine.sync_trade_closures(open_trades, latest_bar=latest_bar):
                self.memory.log_trade_close(closed_trade)
                self.circuit_breaker.record_trade_result(closed_trade.pnl)
                self._ftmo_guard.record_trade_closed(closed_trade.pnl)
                self.telegram.notify(self._format_trade_close_message(closed_trade))

            account = self.engine.account_status()
            self.circuit_breaker.update_balance(
                balance=account.get("balance", 0.0),
                equity=account.get("equity", 0.0),
            )

            sentiment_result = self.sentiment.get_sentiment()
            self.memory.set_runtime_state("last_sentiment", sentiment_result.to_dict())

            current_sentiment = SentimentScore(
                score=sentiment_result.score,
                label=sentiment_result.label,
                headline_count=sentiment_result.headline_count,
                sources=sentiment_result.sources,
                fetched_at=sentiment_result.fetched_at,
            )

            # Update FTMO guard with current equity
            self._ftmo_guard.update_equity(account.get("equity", 0.0))

            cb_status = self.circuit_breaker.get_status_summary()
            self.memory.set_runtime_state("circuit_breaker", cb_status)

            # Persist FTMO status for dashboard
            ftmo_status = self._ftmo_guard.get_status_dict()
            self.memory.set_runtime_state("ftmo_guard", ftmo_status)

            # Check circuit breaker
            if not self.circuit_breaker.can_trade():
                reason = cb_status.get("circuit_description", "circuit breaker actief")
                logger.warning("Trading geblokkeerd door circuit breaker: %s", reason)
                self._update_runtime_state(
                    status="circuit_breaker",
                    circuit_breaker_reason=reason,
                    equity=account.get("equity", 0.0),
                )
                return

            # Check FTMO guard
            if not self._ftmo_guard.can_trade():
                locks = self._ftmo_guard.get_active_locks()
                blocking = [l for l in locks if l.locked and l.severity in ("BLOCK", "CRITICAL")]
                reason = blocking[0].reason if blocking else "FTMO protection active"
                logger.warning("Trading geblokkeerd door FTMO guard: %s", reason)
                self._update_runtime_state(status="ftmo_blocked", ftmo_reason=reason, equity=account.get("equity", 0.0))
                return

            # Check news guard
            news_decision = self._news_guard.check()
            self.memory.set_runtime_state("news_guard", news_decision.to_dict())
            if not news_decision.allow_trading:
                logger.warning("Trading geblokkeerd door news guard: %s", news_decision.reason)
                if news_decision.lock_expires_at:
                    self._ftmo_guard.set_news_lock(news_decision.lock_expires_at)
                self._update_runtime_state(status="news_lock", news_reason=news_decision.reason, equity=account.get("equity", 0.0))
                return

            if control.get("trading_paused", False) or control.get("emergency_stop", False):
                pause_reason = "emergency_stop" if control.get("emergency_stop", False) else "trading_paused"
                self._write_bot_state(account, session_info, sentiment_result, signal=None)
                self._update_runtime_state(
                    status="paused",
                    pause_reason=pause_reason,
                    equity=account.get("equity", 0.0),
                    open_positions=account.get("open_positions", 0),
                    last_signal="trading paused",
                    sentiment_label=current_sentiment.label,
                    sentiment_score=current_sentiment.score,
                    session=session_info.session.value,
                    circuit_breaker_active=cb_status.get("circuit_breaker_active", False),
                    risk_multiplier=self.circuit_breaker.get_risk_multiplier(),
                    signals_enabled=control.get("signals_enabled", True),
                )
                return

            # Haal V20 live config op (hot-reload vanuit live_strategy.json)
            _live_cfg = self.config_manager.get_strategy_cfg()

            signal = None
            if control.get("signals_enabled", True):
                signal = self.brain.generate_signal(
                    enriched,
                    self.parameters,
                    self.settings.symbol,
                    self.settings.timeframe,
                    sentiment=current_sentiment,
                    sentiment_threshold=self.settings.sentiment_filter_threshold,
                    is_killzone=session_info.is_killzone,
                    strategy_cfg=_live_cfg,
                )
                if signal:
                    self._record_signal(signal)

            if signal and not self.engine.has_open_position(self.settings.symbol):
                risk_mult = self.circuit_breaker.get_risk_multiplier()
                # Pattern memory: check if setup is blocked
                sig_type = signal.features.get("signal_type", signal.reason) if isinstance(signal.features, dict) else signal.reason
                h4_regime = signal.market_regime or ""
                # Circuit breaker graduated protection: block disallowed signal types
                if not self.circuit_breaker.is_signal_allowed(sig_type):
                    logger.info(
                        "Signal blocked by circuit breaker (graduated stage %d): %s",
                        self.circuit_breaker.get_graduated_stage(), sig_type,
                    )
                    self._update_runtime_state(status="running", last_signal="blocked by circuit breaker")
                    return
                if self._pattern_memory.is_blocked(sig_type, signal.side, h4_regime=h4_regime):
                    logger.info("Signal blocked by pattern memory: %s %s (low win-rate setup)", sig_type, signal.side)
                    self._update_runtime_state(status="running", last_signal="blocked by pattern memory")
                    return
                execution = self.engine.execute_trade(
                    signal,
                    self.parameters,
                    account_equity=account.get("equity", 0.0),
                    risk_multiplier=risk_mult,
                )
                self._ftmo_guard.record_trade_opened()
                self._pattern_memory.record_trade_opened(
                    sig_type, signal.side, h4_regime=h4_regime,
                    session=session_info.session.value,
                )
                self.memory.log_trade_open(execution, sentiment_score=current_sentiment.score)
                self.telegram.notify(self._format_trade_open_message(
                    execution, signal, session_info, sentiment_result, risk_mult, sig_type,
                ))

            self._write_bot_state(account, session_info, sentiment_result, signal)
            training = self._maybe_train()
            self._maybe_send_daily_report()
            self._update_runtime_state(
                last_bar=latest_closed_bar,
                status="running",
                equity=account.get("equity", 0.0),
                open_positions=account.get("open_positions", 0),
                last_signal=signal.reason if signal else "geen signaal",
                sentiment_label=current_sentiment.label,
                sentiment_score=current_sentiment.score,
                last_training_at=training.trained_at.isoformat() if training else None,
                session=session_info.session.value,
                circuit_breaker_active=cb_status.get("circuit_breaker_active", False),
                risk_multiplier=self.circuit_breaker.get_risk_multiplier(),
                trading_paused=control.get("trading_paused", False),
                emergency_stop=control.get("emergency_stop", False),
                signals_enabled=control.get("signals_enabled", True),
            )
            self.consecutive_errors = 0

        except Exception as exc:
            self.consecutive_errors += 1
            logger.exception("Autonomous cycle mislukt")
            self._update_runtime_state(status="error", last_error=str(exc))
            if self.consecutive_errors >= self.settings.max_consecutive_errors:
                self.stop_requested = True
                self.telegram.notify(f"Engine gestopt na {self.consecutive_errors} opeenvolgende fouten: {exc}")

    def _write_bot_state(self, account: dict, session_info, sentiment_result, signal) -> None:
        try:
            _BOT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            existing: dict[str, object] = {}
            if _BOT_STATE_PATH.exists():
                try:
                    existing = json.loads(_BOT_STATE_PATH.read_text(encoding="utf-8"))
                except Exception:
                    existing = {}

            signal_history = existing.get("signal_history", [])
            if not isinstance(signal_history, list):
                signal_history = []

            state = {
                "balance": account.get("balance", 0.0),
                "equity": account.get("equity", 0.0),
                "open_positions": account.get("positions", []),
                "mode": self.settings.mode,
                "last_signal_time": signal.opened_at.isoformat() if signal else existing.get("last_signal_time"),
                "last_signal": existing.get("last_signal"),
                "signal_history": signal_history[-100:],
                "signals_today": sum(
                    1 for item in signal_history if str(item.get("time", "")).startswith(datetime.now(timezone.utc).strftime("%Y-%m-%d"))
                ),
                "cycle_count": int(existing.get("cycle_count", 0)) + 1,
                "day_start_equity": account.get("day_start_equity", existing.get("day_start_equity", account.get("balance", 0.0))),
                "last_sentiment": sentiment_result.to_dict(),
                "circuit_breaker": self.circuit_breaker.get_status_summary(),
                "session": session_info.to_dict(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            _BOT_STATE_PATH.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
        except Exception as exc:
            logger.debug("Bot state schrijven mislukt: %s", exc)

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

    def _maybe_send_daily_report(self) -> None:
        report_state = self.memory.get_runtime_state("daily_report")
        now = datetime.now(timezone.utc)
        if now.hour < self.settings.daily_report_hour_utc:
            return
        if report_state and report_state.get("day") == now.date().isoformat():
            return

        summary = self.memory.daily_summary(now.date())
        sentiment = self.memory.get_runtime_state("last_sentiment") or {}
        self.telegram.notify(
            f"Dagrapport {summary['day']}: trades={summary['trade_count']}, "
            f"PnL={summary['realized_pnl']:.2f}, win-rate={summary['win_rate']:.2%}\n"
            f"Sentiment: {sentiment.get('label', 'n.v.t.')} ({sentiment.get('score', 0.0):.2f})"
        )
        self.memory.set_runtime_state("daily_report", {"day": now.date().isoformat(), "sent_at": now.isoformat()})

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
            command_id = int(command["id"])
            action = str(command["command"])
            try:
                self.memory.update_control_command(command_id, "executing", result_message="Command in uitvoering.")
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
            self.memory.set_bot_control_state(bot_active=True, trading_paused=False, emergency_stop=False)
            return "Trading hervat."
        if action == "emergency_stop":
            self.memory.set_bot_control_state(bot_active=False, trading_paused=True, emergency_stop=True)
            return "Emergency stop bevestigd. Nieuwe trades zijn uitgeschakeld."
        if action == "close_all_positions":
            closed = self.engine.close_all_positions(symbol=self.settings.symbol, reason="telegram_close_all")
            for trade in closed:
                self.memory.log_trade_close(trade)
            return f"Alle posities gesloten: {len(closed)}."
        if action == "train_ai":
            outcome = self._run_training_cycle()
            if outcome is None:
                return "AI training overgeslagen: onvoldoende gesloten trades."
            return f"AI training voltooid. Accuracy={outcome.accuracy:.2%}, samples={outcome.sample_count}."
        raise ValueError(f"Unsupported control command: {action}")

    def _format_trade_open_message(self, execution, signal, session_info, sentiment_result, risk_mult: float, sig_type: str) -> str:
        direction_emoji = "🟢 LONG" if execution.side.lower() == "buy" else "🔴 SHORT"
        sl_pts = abs(execution.entry_price - execution.stop_loss)
        tp_pts = abs(execution.take_profit - execution.entry_price)
        rr = tp_pts / sl_pts if sl_pts > 0 else 0.0
        regime = execution.market_regime or "unknown"
        features = execution.features if isinstance(execution.features, dict) else {}
        confidence = features.get("confidence", features.get("ml_confidence", 0.0))
        pat_mult = self._pattern_memory.get_risk_multiplier(
            sig_type, execution.side,
            h4_regime=regime,
            session=session_info.session.value,
        )
        ftmo = self._ftmo_guard.get_status_dict()
        daily_remaining = ftmo.get("daily_remaining", ftmo.get("daily_loss_limit", 6000))
        total_remaining = ftmo.get("total_dd_limit", 16000) - ftmo.get("total_drawdown", 0)

        lines = [
            f"{direction_emoji} TRADE GEOPEND — {execution.symbol}",
            f"",
            f"Signaal:    {sig_type}",
            f"Entry:      {execution.entry_price:.2f}",
            f"Stop Loss:  {execution.stop_loss:.2f}  ({sl_pts:.1f} pts)",
            f"Take Profit:{execution.take_profit:.2f}  ({tp_pts:.1f} pts)",
            f"R:R ratio:  1:{rr:.1f}",
            f"Lot size:   {execution.volume:.2f}",
            f"",
            f"Sessie:     {session_info.session.value.upper()}",
            f"Regime:     {regime}",
            f"Sentiment:  {sentiment_result.label} ({sentiment_result.score:+.2f})",
        ]
        if confidence:
            lines.append(f"ML conf:    {float(confidence):.1%}")
        lines += [
            f"Risk mult:  CB={risk_mult:.0%}  PAT={pat_mult:.0%}",
            f"",
            f"FTMO ruimte:",
            f"  Dag:      €{daily_remaining:,.0f} resterend",
            f"  Totaal:   €{total_remaining:,.0f} resterend",
            f"",
            f"Mode: {execution.mode.upper()}  |  Ticket: {execution.broker_ticket}",
        ]
        return "\n".join(lines)

    def _format_trade_close_message(self, closed_trade) -> str:
        won = closed_trade.pnl >= 0
        result_emoji = "✅ WIN" if won else "❌ VERLIES"
        reason_map = {"tp": "TP geraakt", "sl": "SL geraakt", "manual": "Manueel", "telegram_close_all": "Emergency close"}
        reason_label = reason_map.get(closed_trade.close_reason.lower(), closed_trade.close_reason)
        ftmo = self._ftmo_guard.get_status_dict()
        daily_used = ftmo.get("daily_loss_used", 0)
        daily_limit = ftmo.get("daily_loss_limit", 6000)
        total_dd = ftmo.get("total_drawdown", 0)
        daily_pct = (daily_used / daily_limit * 100) if daily_limit else 0

        lines = [
            f"{result_emoji} — XAUUSD trade gesloten",
            f"",
            f"Exit:       {closed_trade.exit_price:.2f}",
            f"PnL:        €{closed_trade.pnl:+,.2f}",
            f"Reden:      {reason_label}",
            f"",
            f"FTMO na trade:",
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
            _BOT_STATE_PATH.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
        except Exception as exc:
            logger.debug("Signal history write failed: %s", exc)


def main() -> None:
    AutonomousTradingSystem().run_forever()
