"""
WebSocket Stream Service — Periodic data pusher to all connected clients.

Runs as a background asyncio task started in the FastAPI lifespan.
Every N seconds it reads fresh state from the database/runtime and
broadcasts it to the appropriate WebSocket channel.

Push schedule:
  equity       → every 5 seconds
  sentiment    → every 60 seconds
  risk         → every 30 seconds
  regime       → every 30 seconds
  news         → every 120 seconds
  heartbeat    → every 15 seconds
  ml           → every 300 seconds
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
_UTC = timezone.utc
_BOT_STATE = Path("live_logs/bot_state.json")
_HEARTBEAT = Path("live_logs/heartbeat.json")


class WsStreamService:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._running = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._last_positions_signature: str | None = None
        self._last_signal_signature: str | None = None
        self._last_execution_signature: str | None = None

    def start(self) -> None:
        current_loop = asyncio.get_running_loop()
        if self._loop is not current_loop:
            self._loop = current_loop
            self._task = None

        if self._task is None or self._task.done():
            self._running = True
            self._task = asyncio.create_task(self._stream_loop())
            logger.info("WsStreamService: started")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            finally:
                self._task = None

    async def _stream_loop(self) -> None:
        tick = 0
        while self._running:
            try:
                await self._push_equity()
                await self._push_positions()
                await self._push_signal()
                await self._push_execution()

                if tick % 3 == 0:   # every 15s
                    await self._push_heartbeat()

                if tick % 6 == 0:   # every 30s
                    await self._push_risk()
                    await self._push_regime()

                if tick % 12 == 0:  # every 60s
                    await self._push_sentiment()

                if tick % 24 == 0:  # every 2 min
                    await self._push_news()

                if tick % 60 == 0:  # every 5 min
                    await self._push_ml()

            except Exception as exc:
                logger.debug("WsStreamService loop error: %s", exc)

            tick = (tick + 1) % 10000
            await asyncio.sleep(5)

    async def snapshot_messages(self, channels: set[str] | list[str] | None = None) -> list[dict[str, Any]]:
        requested = set(channels or [])
        if not requested:
            requested = {
                "equity",
                "positions",
                "trades",
                "risk",
                "regime",
                "sentiment",
                "news",
                "heartbeat",
                "ml",
                "execution",
            }

        messages: list[dict[str, Any]] = []

        equity = self._build_equity_payload()
        if equity and "equity" in requested:
            messages.append(self._event_message("equity.update", "equity", equity))

        positions = self._build_positions_payload()
        if positions and "positions" in requested:
            messages.append(self._event_message("positions.update", "positions", positions))

        signal = self._build_signal_payload()
        if signal and "trades" in requested:
            messages.append(self._event_message("signal.detected", "trades", signal))

        execution = self._build_execution_payload()
        if execution and "execution" in requested:
            messages.append(self._event_message("execution.update", "execution", execution))

        heartbeat = self._build_heartbeat_payload()
        if heartbeat and "heartbeat" in requested:
            messages.append(self._event_message("heartbeat", "heartbeat", heartbeat))

        risk = self._build_risk_payload()
        if risk and "risk" in requested:
            messages.append(self._event_message("risk.update", "risk", risk))

        regime = self._build_regime_payload()
        if regime and "regime" in requested:
            messages.append(self._event_message("regime.change", "regime", regime))

        sentiment = self._build_sentiment_payload()
        if sentiment and "sentiment" in requested:
            messages.append(self._event_message("sentiment.update", "sentiment", sentiment))

        news = self._build_news_payload()
        if news and "news" in requested:
            messages.append(self._event_message("news.update", "news", news))

        ml = self._build_ml_payload()
        if ml and "ml" in requested:
            messages.append(self._event_message("ml.update", "ml", ml))

        return messages

    async def _push_equity(self) -> None:
        try:
            from backend.websocket.manager import ws_manager
            payload = self._build_equity_payload()
            if payload is None:
                return
            await ws_manager.push_equity_update(
                equity=float(payload["equity"]),
                balance=float(payload["balance"]),
                drawdown_pct=float(payload["drawdown_pct"]),
            )
        except Exception as exc:
            logger.debug("_push_equity: %s", exc)

    async def _push_positions(self) -> None:
        try:
            from backend.websocket.manager import ws_manager

            payload = self._build_positions_payload()
            if payload is None:
                return

            signature = self._signature(payload)
            if signature == self._last_positions_signature:
                return

            self._last_positions_signature = signature
            await ws_manager.push_positions(payload)
        except Exception as exc:
            logger.debug("_push_positions: %s", exc)

    async def _push_signal(self) -> None:
        try:
            from backend.websocket.manager import ws_manager

            payload = self._build_signal_payload()
            if payload is None:
                return

            signature = self._signature(payload)
            if signature == self._last_signal_signature:
                return

            self._last_signal_signature = signature
            await ws_manager.push_signal(payload)
        except Exception as exc:
            logger.debug("_push_signal: %s", exc)

    async def _push_execution(self) -> None:
        try:
            from backend.websocket.manager import ws_manager

            payload = self._build_execution_payload()
            if payload is None:
                return

            signature = self._signature(payload)
            if signature == self._last_execution_signature:
                return

            self._last_execution_signature = signature
            await ws_manager.push_execution(payload)
        except Exception as exc:
            logger.debug("_push_execution: %s", exc)

    async def _push_sentiment(self) -> None:
        try:
            from backend.websocket.manager import ws_manager
            sentiment = self._build_sentiment_payload()
            if sentiment is None:
                return
            await ws_manager.push_sentiment(sentiment)
        except Exception as exc:
            logger.debug("_push_sentiment: %s", exc)

    async def _push_risk(self) -> None:
        try:
            from backend.websocket.manager import ws_manager

            risk_payload = self._build_risk_payload()
            if risk_payload is None:
                return
            await ws_manager.push_risk(risk_payload)
        except Exception as exc:
            logger.debug("_push_risk: %s", exc)

    async def _push_regime(self) -> None:
        try:
            from backend.websocket.manager import ws_manager

            regime = self._build_regime_payload()
            if regime is None:
                return
            await ws_manager.push_regime(regime)
        except Exception as exc:
            logger.debug("_push_regime: %s", exc)

    async def _push_news(self) -> None:
        try:
            from backend.websocket.manager import ws_manager
            payload = self._build_news_payload()
            if payload is None:
                return
            await ws_manager.push_news(payload)
        except Exception as exc:
            logger.debug("_push_news: %s", exc)

    async def _push_heartbeat(self) -> None:
        try:
            from backend.websocket.manager import ws_manager

            payload = self._build_heartbeat_payload()
            if payload is None:
                return
            await ws_manager.push_heartbeat(payload)
        except Exception as exc:
            logger.debug("_push_heartbeat: %s", exc)

    async def _push_ml(self) -> None:
        try:
            from backend.websocket.manager import ws_manager

            payload = self._build_ml_payload()
            if payload is None:
                return
            await ws_manager.push_ml_update(payload)
        except Exception as exc:
            logger.debug("_push_ml: %s", exc)

    def _build_equity_payload(self) -> dict[str, Any] | None:
        state = _read_bot_state()
        if state is None:
            return None

        balance = float(state.get("balance", 0.0))
        equity = float(state.get("equity", 0.0))
        start_eq = float(state.get("day_start_equity", balance))
        dd_pct = ((start_eq - equity) / start_eq * 100) if start_eq > 0 else 0.0
        return {
            "equity": round(equity, 2),
            "balance": round(balance, 2),
            "drawdown_pct": round(max(0.0, dd_pct), 3),
        }

    def _build_positions_payload(self) -> dict[str, Any] | None:
        state = _read_bot_state()
        if state is None:
            return None

        positions = state.get("open_positions", [])
        if not isinstance(positions, list):
            positions = []

        floating_pnl = round(sum(float(position.get("profit", 0.0) or 0.0) for position in positions), 2)
        return {
            "positions": positions,
            "count": len(positions),
            "floating_pnl": floating_pnl,
            "updated_at": state.get("updated_at"),
        }

    def _build_signal_payload(self) -> dict[str, Any] | None:
        state = _read_bot_state()
        if state is None:
            return None

        payload = state.get("last_signal")
        if not isinstance(payload, dict) or not payload:
            return None

        signal_payload = dict(payload)
        signal_payload.setdefault("time", state.get("last_signal_time"))
        return signal_payload

    def _build_execution_payload(self) -> dict[str, Any] | None:
        engine_state = self._load_runtime_state("engine_status") or {}
        state = _read_bot_state() or {}

        if not engine_state and not state:
            return None

        positions = state.get("open_positions", [])
        if not isinstance(positions, list):
            positions = []

        return {
            "status": engine_state.get("status", "unknown"),
            "mode": engine_state.get("mode", state.get("mode", "unknown")),
            "symbol": engine_state.get("symbol", "XAUUSD"),
            "timeframe": engine_state.get("timeframe"),
            "last_signal": engine_state.get("last_signal", state.get("last_signal")),
            "trading_paused": bool(engine_state.get("trading_paused", False)),
            "emergency_stop": bool(engine_state.get("emergency_stop", False)),
            "open_positions": len(positions),
            "updated_at": engine_state.get("updated_at", state.get("updated_at")),
        }

    def _build_sentiment_payload(self) -> dict[str, Any] | None:
        state = _read_bot_state()
        if state is None:
            return None

        sentiment = state.get("last_sentiment")
        return sentiment if isinstance(sentiment, dict) and sentiment else None

    def _build_risk_payload(self) -> dict[str, Any] | None:
        cb = self._load_runtime_state("circuit_breaker") or {}
        state = _read_bot_state() or {}
        equity = float(state.get("equity", 160000.0))
        start_eq = float(state.get("day_start_equity", equity))
        return {
            "circuit_breaker_active": cb.get("circuit_breaker_active", False),
            "risk_multiplier": cb.get("risk_multiplier", 1.0),
            "daily_loss": round(max(0.0, start_eq - equity), 2),
            "daily_loss_pct": round(max(0.0, (start_eq - equity) / start_eq * 100) if start_eq > 0 else 0.0, 2),
            "can_trade": not cb.get("circuit_breaker_active", False),
        }

    def _build_regime_payload(self) -> dict[str, Any] | None:
        engine_state = self._load_runtime_state("engine_status") or {}
        if not engine_state:
            return None

        return {
            "session": engine_state.get("session", "unknown"),
            "status": engine_state.get("status", "unknown"),
            "last_signal": engine_state.get("last_signal", ""),
        }

    def _build_news_payload(self) -> dict[str, Any] | None:
        news_cache = Path("live_logs/news_cache.json")
        if not news_cache.exists():
            return None

        data = json.loads(news_cache.read_text(encoding="utf-8"))
        return {
            "composite_sentiment": data.get("composite_sentiment", 0.0),
            "danger_score": data.get("danger_score", 0.0),
            "high_impact_count": data.get("high_impact_count", 0),
            "total_headlines": data.get("total_headlines", 0),
            "top_keywords": data.get("top_keywords", [])[:6],
            "should_pause": data.get("should_pause_trading", False),
        }

    def _build_heartbeat_payload(self) -> dict[str, Any] | None:
        if _HEARTBEAT.exists():
            return json.loads(_HEARTBEAT.read_text(encoding="utf-8"))

        return {
            "status": "api_only",
            "ts": datetime.now(_UTC).isoformat(),
            "trading_bot_running": False,
        }

    def _build_ml_payload(self) -> dict[str, Any] | None:
        model_hist = self._load_model_history()
        if model_hist is None or model_hist.empty:
            return None

        latest = model_hist.iloc[-1]
        return {
            "accuracy": latest.get("accuracy", 0.0),
            "f1_score": latest.get("f1_score", 0.0),
            "sample_count": latest.get("sample_count", 0),
            "trained_at": latest.get("trained_at", ""),
        }

    def _load_runtime_state(self, key: str) -> dict[str, Any] | None:
        from autonomous_xauusd.memory_layer import MemoryLayer
        from backend.core.config import get_settings

        settings = get_settings()
        memory = MemoryLayer(settings.database_url)
        state = memory.get_runtime_state(key)
        return state if isinstance(state, dict) else None

    def _load_model_history(self):
        from autonomous_xauusd.memory_layer import MemoryLayer
        from backend.core.config import get_settings

        settings = get_settings()
        memory = MemoryLayer(settings.database_url)
        return memory.model_history()

    def _event_message(self, event_type: str, channel: str, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": event_type,
            "channel": channel,
            "payload": payload,
            "ts": datetime.now(_UTC).isoformat(),
        }

    def _signature(self, payload: dict[str, Any]) -> str:
        return json.dumps(payload, sort_keys=True, default=str)


def _read_bot_state() -> dict[str, Any] | None:
    try:
        if _BOT_STATE.exists():
            import json
            return json.loads(_BOT_STATE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


_stream_service = WsStreamService()


def get_stream_service() -> WsStreamService:
    return _stream_service
