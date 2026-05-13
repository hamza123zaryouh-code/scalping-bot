from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

from .analytics_engine import compute_report
from .brain_layer import IntelligenceLayer
from .communication_layer import TelegramControlLayer
from .data_layer import DataExecutionLayer
from .memory_layer import MemoryLayer
from .models import TrainingOutcome
from .sentiment_layer import SentimentLayer
from .settings import XAUUSDSettings, load_settings


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


class AutonomousTradingSystem:
    def __init__(self, settings: XAUUSDSettings | None = None) -> None:
        self.settings = settings or load_settings()
        self.memory = MemoryLayer(self.settings.database_url)
        self.memory.initialize()
        self.parameters = self.memory.load_strategy_parameters(self.settings.default_parameters)
        self.memory.save_strategy_parameters(self.parameters, source="bootstrap")
        self.brain = IntelligenceLayer(self.settings.model_artifact_path)
        self.engine = DataExecutionLayer(self.settings)
        self.sentiment = SentimentLayer(
            symbol=self.settings.sentiment_symbol,
            cache_minutes=self.settings.sentiment_cache_minutes,
        )
        self.stop_requested = False
        self.consecutive_errors = 0
        self.last_processed_bar: str | None = None

        self.telegram = TelegramControlLayer(
            token=self.settings.telegram_bot_token,
            chat_id=self.settings.telegram_chat_id,
            status_callback=self._status_text,
            stop_callback=self.request_stop,
            train_callback=self.train_now,
        )

    def request_stop(self) -> str:
        self.stop_requested = True
        return "Emergency stop geactiveerd. De engine stopt na de huidige cyclus."

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
        return (
            f"Status: {runtime.get('status', 'idle')}\n"
            f"Mode: {runtime.get('mode', self.settings.mode)}\n"
            f"Symbool: {runtime.get('symbol', self.settings.symbol)} {runtime.get('timeframe', self.settings.timeframe)}\n"
            f"Open posities: {runtime.get('open_positions', 0)}\n"
            f"Equity: {runtime.get('equity', 0.0):.2f}\n"
            f"Sentiment: {sentiment.get('label', 'n.v.t.')} ({sentiment.get('score', 0.0):.2f})\n"
            f"Laatste bar: {runtime.get('last_bar', 'n.v.t.')}\n"
            f"Laatste training: {runtime.get('last_training_at', 'nog niet')}"
        )

    def run_forever(self) -> None:
        if not self.engine.connect():
            raise RuntimeError("Data/execution layer kon niet starten. Controleer MT5, CCXT of paper fallback.")

        self.telegram.start_in_background()
        self.telegram.notify(
            f"Autonomous XAUUSD systeem gestart in {self.settings.mode} mode voor {self.settings.symbol} {self.settings.timeframe}."
        )

        try:
            while not self.stop_requested:
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
                    "stopped_at": datetime.utcnow().isoformat(),
                },
            )

    def _run_cycle(self) -> None:
        try:
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

            account = self.engine.account_status()

            # Sentiment ophalen en opslaan
            current_sentiment = self.sentiment.get_sentiment()
            self.memory.set_runtime_state("last_sentiment", {
                "score": current_sentiment.score,
                "label": current_sentiment.label,
                "headline_count": current_sentiment.headline_count,
                "fetched_at": current_sentiment.fetched_at.isoformat(),
                "sources": current_sentiment.sources,
            })

            signal = self.brain.generate_signal(
                enriched,
                self.parameters,
                self.settings.symbol,
                self.settings.timeframe,
                sentiment=current_sentiment,
                sentiment_threshold=self.settings.sentiment_filter_threshold,
            )

            if signal and not self.engine.has_open_position(self.settings.symbol):
                execution = self.engine.execute_trade(signal, self.parameters, account_equity=account["equity"])
                self.memory.log_trade_open(execution, sentiment_score=current_sentiment.score)
                self.telegram.notify(
                    f"Trade geopend: {execution.side.upper()} {execution.symbol} @ {execution.entry_price:.2f} | "
                    f"SL {execution.stop_loss:.2f} | TP {execution.take_profit:.2f} | "
                    f"Sentiment: {current_sentiment.label} | mode={execution.mode}"
                )

            training = self._maybe_train()
            self._maybe_send_daily_report()
            self._update_runtime_state(
                last_bar=latest_closed_bar,
                status="running",
                equity=account["equity"],
                open_positions=account["open_positions"],
                last_signal=signal.reason if signal else "geen signaal",
                sentiment_label=current_sentiment.label,
                sentiment_score=current_sentiment.score,
                last_training_at=training.trained_at.isoformat() if training else None,
            )
            self.consecutive_errors = 0
        except Exception as exc:
            self.consecutive_errors += 1
            logger.exception("Autonomous cycle mislukt")
            self._update_runtime_state(status="error", last_error=str(exc))
            if self.consecutive_errors >= self.settings.max_consecutive_errors:
                self.stop_requested = True
                self.telegram.notify(f"Engine gestopt na {self.consecutive_errors} opeenvolgende fouten: {exc}")

    def _run_training_cycle(self) -> TrainingOutcome | None:
        trade_frame = self.memory.fetch_training_frame()
        outcome = self.brain.train_model(trade_frame, self.parameters)
        if outcome is None:
            return None

        self.memory.save_model_snapshot(outcome)
        if outcome.parameter_overrides:
            self.parameters = self.parameters.with_overrides(outcome.parameter_overrides)
            self.memory.save_strategy_parameters(self.parameters, source="ml_feedback_loop")

        # Analytics rapport genereren na training
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
            if datetime.utcnow() - trained_at < timedelta(days=self.settings.train_every_days):
                return None
        return self._run_training_cycle()

    def _maybe_send_daily_report(self) -> None:
        report_state = self.memory.get_runtime_state("daily_report")
        now = datetime.utcnow()
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
            "updated_at": datetime.utcnow().isoformat(),
        }
        self.memory.set_runtime_state("engine_status", merged)


def main() -> None:
    AutonomousTradingSystem().run_forever()
