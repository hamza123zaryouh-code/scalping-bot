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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
_UTC = timezone.utc
_BOT_STATE = Path("live_logs/bot_state.json")
_HEARTBEAT = Path("live_logs/heartbeat.json")
_NEWS_CACHE = Path("live_logs/news_cache.json")


@dataclass(slots=True)
class _StreamSnapshot:
    bot_state: dict[str, Any] = field(default_factory=dict)
    runtime_state: dict[str, dict[str, Any] | None] = field(default_factory=dict)
    heartbeat: dict[str, Any] | None = None
    news: dict[str, Any] | None = None
    model_history: Any = None


class WsStreamService:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._running = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._last_positions_signature: str | None = None
        self._last_signal_signature: str | None = None
        self._last_execution_signature: str | None = None
        self._memory = None
        self._memory_database_url: str | None = None

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
                snapshot = self._collect_snapshot(
                    runtime_keys={"engine_status", "circuit_breaker"},
                    include_heartbeat=tick % 3 == 0,
                    include_news=tick % 24 == 0,
                    include_model_history=tick % 60 == 0,
                )

                await self._push_equity(snapshot)
                await self._push_positions(snapshot)
                await self._push_signal(snapshot)
                await self._push_execution(snapshot)

                if tick % 3 == 0:   # every 15s
                    await self._push_heartbeat(snapshot)

                if tick % 6 == 0:   # every 30s
                    await self._push_risk(snapshot)
                    await self._push_regime(snapshot)

                if tick % 12 == 0:  # every 60s
                    await self._push_sentiment(snapshot)

                if tick % 24 == 0:  # every 2 min
                    await self._push_news(snapshot)

                if tick % 60 == 0:  # every 5 min
                    await self._push_ml(snapshot)

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

        runtime_keys: set[str] = set()
        if {"risk"} & requested:
            runtime_keys.add("circuit_breaker")
        if {"regime", "execution"} & requested:
            runtime_keys.add("engine_status")

        snapshot = self._collect_snapshot(
            runtime_keys=runtime_keys,
            include_heartbeat="heartbeat" in requested,
            include_news="news" in requested,
            include_model_history="ml" in requested,
        )
        messages: list[dict[str, Any]] = []

        if "equity" in requested:
            equity = self._build_equity_payload(snapshot)
        else:
            equity = None
        if equity:
            messages.append(self._event_message("equity.update", "equity", equity))

        if "positions" in requested:
            positions = self._build_positions_payload(snapshot)
        else:
            positions = None
        if positions:
            messages.append(self._event_message("positions.update", "positions", positions))

        if "trades" in requested:
            signal = self._build_signal_payload(snapshot)
        else:
            signal = None
        if signal:
            messages.append(self._event_message("signal.detected", "trades", signal))

        if "execution" in requested:
            execution = self._build_execution_payload(snapshot)
        else:
            execution = None
        if execution:
            messages.append(self._event_message("execution.update", "execution", execution))

        if "heartbeat" in requested:
            heartbeat = self._build_heartbeat_payload(snapshot)
        else:
            heartbeat = None
        if heartbeat:
            messages.append(self._event_message("heartbeat", "heartbeat", heartbeat))

        if "risk" in requested:
            risk = self._build_risk_payload(snapshot)
        else:
            risk = None
        if risk:
            messages.append(self._event_message("risk.update", "risk", risk))

        if "regime" in requested:
            regime = self._build_regime_payload(snapshot)
        else:
            regime = None
        if regime:
            messages.append(self._event_message("regime.change", "regime", regime))

        if "sentiment" in requested:
            sentiment = self._build_sentiment_payload(snapshot)
        else:
            sentiment = None
        if sentiment:
            messages.append(self._event_message("sentiment.update", "sentiment", sentiment))

        if "news" in requested:
            news = self._build_news_payload(snapshot)
        else:
            news = None
        if news:
            messages.append(self._event_message("news.update", "news", news))

        if "ml" in requested:
            ml = self._build_ml_payload(snapshot)
        else:
            ml = None
        if ml:
            messages.append(self._event_message("ml.update", "ml", ml))

        return messages

    async def _push_equity(self, snapshot: _StreamSnapshot | None = None) -> None:
        try:
            from backend.websocket.manager import ws_manager
            payload = self._build_equity_payload(snapshot)
            if payload is None:
                return
            await ws_manager.push_equity_update(
                equity=float(payload["equity"]),
                balance=float(payload["balance"]),
                drawdown_pct=float(payload["drawdown_pct"]),
            )
        except Exception as exc:
            logger.debug("_push_equity: %s", exc)

    async def _push_positions(self, snapshot: _StreamSnapshot | None = None) -> None:
        try:
            from backend.websocket.manager import ws_manager

            payload = self._build_positions_payload(snapshot)
            if payload is None:
                return

            signature = self._signature(payload)
            if signature == self._last_positions_signature:
                return

            self._last_positions_signature = signature
            await ws_manager.push_positions(payload)
        except Exception as exc:
            logger.debug("_push_positions: %s", exc)

    async def _push_signal(self, snapshot: _StreamSnapshot | None = None) -> None:
        try:
            from backend.websocket.manager import ws_manager

            payload = self._build_signal_payload(snapshot)
            if payload is None:
                return

            signature = self._signature(payload)
            if signature == self._last_signal_signature:
                return

            self._last_signal_signature = signature
            await ws_manager.push_signal(payload)
        except Exception as exc:
            logger.debug("_push_signal: %s", exc)

    async def _push_execution(self, snapshot: _StreamSnapshot | None = None) -> None:
        try:
            from backend.websocket.manager import ws_manager

            payload = self._build_execution_payload(snapshot)
            if payload is None:
                return

            signature = self._signature(payload)
            if signature == self._last_execution_signature:
                return

            self._last_execution_signature = signature
            await ws_manager.push_execution(payload)
        except Exception as exc:
            logger.debug("_push_execution: %s", exc)

    async def _push_sentiment(self, snapshot: _StreamSnapshot | None = None) -> None:
        try:
            from backend.websocket.manager import ws_manager
            sentiment = self._build_sentiment_payload(snapshot)
            if sentiment is None:
                return
            await ws_manager.push_sentiment(sentiment)
        except Exception as exc:
            logger.debug("_push_sentiment: %s", exc)

    async def _push_risk(self, snapshot: _StreamSnapshot | None = None) -> None:
        try:
            from backend.websocket.manager import ws_manager

            risk_payload = self._build_risk_payload(snapshot)
            if risk_payload is None:
                return
            await ws_manager.push_risk(risk_payload)
        except Exception as exc:
            logger.debug("_push_risk: %s", exc)

    async def _push_regime(self, snapshot: _StreamSnapshot | None = None) -> None:
        try:
            from backend.websocket.manager import ws_manager

            regime = self._build_regime_payload(snapshot)
            if regime is None:
                return
            await ws_manager.push_regime(regime)
        except Exception as exc:
            logger.debug("_push_regime: %s", exc)

    async def _push_news(self, snapshot: _StreamSnapshot | None = None) -> None:
        try:
            from backend.websocket.manager import ws_manager
            payload = self._build_news_payload(snapshot)
            if payload is None:
                return
            await ws_manager.push_news(payload)
        except Exception as exc:
            logger.debug("_push_news: %s", exc)

    async def _push_heartbeat(self, snapshot: _StreamSnapshot | None = None) -> None:
        try:
            from backend.websocket.manager import ws_manager

            payload = self._build_heartbeat_payload(snapshot)
            if payload is None:
                return
            await ws_manager.push_heartbeat(payload)
        except Exception as exc:
            logger.debug("_push_heartbeat: %s", exc)

    async def _push_ml(self, snapshot: _StreamSnapshot | None = None) -> None:
        try:
            from backend.websocket.manager import ws_manager

            payload = self._build_ml_payload(snapshot)
            if payload is None:
                return
            await ws_manager.push_ml_update(payload)
        except Exception as exc:
            logger.debug("_push_ml: %s", exc)

    def _build_equity_payload(self, snapshot: _StreamSnapshot | None = None) -> dict[str, Any] | None:
        state = self._bot_state(snapshot)
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

    def _build_positions_payload(self, snapshot: _StreamSnapshot | None = None) -> dict[str, Any] | None:
        state = self._bot_state(snapshot)
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

    def _build_signal_payload(self, snapshot: _StreamSnapshot | None = None) -> dict[str, Any] | None:
        state = self._bot_state(snapshot)
        if state is None:
            return None

        payload = state.get("last_signal")
        if not isinstance(payload, dict) or not payload:
            return None

        signal_payload = dict(payload)
        signal_payload.setdefault("time", state.get("last_signal_time"))
        return signal_payload

    def _build_execution_payload(self, snapshot: _StreamSnapshot | None = None) -> dict[str, Any] | None:
        engine_state = self._runtime_state(snapshot, "engine_status") or {}
        state = self._bot_state(snapshot) or {}

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

    def _build_sentiment_payload(self, snapshot: _StreamSnapshot | None = None) -> dict[str, Any] | None:
        state = self._bot_state(snapshot)
        if state is None:
            return None

        sentiment = state.get("last_sentiment")
        return sentiment if isinstance(sentiment, dict) and sentiment else None

    def _build_risk_payload(self, snapshot: _StreamSnapshot | None = None) -> dict[str, Any] | None:
        cb = self._runtime_state(snapshot, "circuit_breaker") or {}
        state = self._bot_state(snapshot) or {}
        equity = float(state.get("equity", 160000.0))
        start_eq = float(state.get("day_start_equity", equity))
        return {
            "circuit_breaker_active": cb.get("circuit_breaker_active", False),
            "risk_multiplier": cb.get("risk_multiplier", 1.0),
            "daily_loss": round(max(0.0, start_eq - equity), 2),
            "daily_loss_pct": round(max(0.0, (start_eq - equity) / start_eq * 100) if start_eq > 0 else 0.0, 2),
            "can_trade": not cb.get("circuit_breaker_active", False),
        }

    def _build_regime_payload(self, snapshot: _StreamSnapshot | None = None) -> dict[str, Any] | None:
        engine_state = self._runtime_state(snapshot, "engine_status") or {}
        if not engine_state:
            return None

        return {
            "session": engine_state.get("session", "unknown"),
            "status": engine_state.get("status", "unknown"),
            "last_signal": engine_state.get("last_signal", ""),
        }

    def _build_news_payload(self, snapshot: _StreamSnapshot | None = None) -> dict[str, Any] | None:
        data = self._news_payload_source(snapshot)
        if data is None:
            return None

        return {
            "composite_sentiment": data.get("composite_sentiment", 0.0),
            "danger_score": data.get("danger_score", 0.0),
            "high_impact_count": data.get("high_impact_count", 0),
            "total_headlines": data.get("total_headlines", 0),
            "top_keywords": data.get("top_keywords", [])[:6],
            "should_pause": data.get("should_pause_trading", False),
        }

    def _build_heartbeat_payload(self, snapshot: _StreamSnapshot | None = None) -> dict[str, Any] | None:
        payload = self._heartbeat_payload_source(snapshot)
        if payload is not None:
            return payload

        return {
            "status": "api_only",
            "ts": datetime.now(_UTC).isoformat(),
            "trading_bot_running": False,
        }

    def _build_ml_payload(self, snapshot: _StreamSnapshot | None = None) -> dict[str, Any] | None:
        model_hist = snapshot.model_history if snapshot is not None else self._load_model_history()
        if model_hist is None or model_hist.empty:
            return None

        latest = model_hist.iloc[-1]
        return {
            "accuracy": latest.get("accuracy", 0.0),
            "f1_score": latest.get("f1_score", 0.0),
            "sample_count": latest.get("sample_count", 0),
            "trained_at": latest.get("trained_at", ""),
        }

    def _collect_snapshot(
        self,
        *,
        runtime_keys: set[str] | None = None,
        include_heartbeat: bool = False,
        include_news: bool = False,
        include_model_history: bool = False,
    ) -> _StreamSnapshot:
        runtime_state = {
            key: self._load_runtime_state(key)
            for key in sorted(runtime_keys or set())
        }
        return _StreamSnapshot(
            bot_state=_read_bot_state() or {},
            runtime_state=runtime_state,
            heartbeat=_read_json_file(_HEARTBEAT) if include_heartbeat else None,
            news=_read_json_file(_NEWS_CACHE) if include_news else None,
            model_history=self._load_model_history() if include_model_history else None,
        )

    def _bot_state(self, snapshot: _StreamSnapshot | None) -> dict[str, Any] | None:
        return snapshot.bot_state if snapshot is not None else _read_bot_state()

    def _runtime_state(self, snapshot: _StreamSnapshot | None, key: str) -> dict[str, Any] | None:
        if snapshot is not None and key in snapshot.runtime_state:
            value = snapshot.runtime_state[key]
            return value if isinstance(value, dict) else None
        return self._load_runtime_state(key)

    def _heartbeat_payload_source(self, snapshot: _StreamSnapshot | None) -> dict[str, Any] | None:
        if snapshot is not None:
            return snapshot.heartbeat if isinstance(snapshot.heartbeat, dict) else None
        return _read_json_file(_HEARTBEAT)

    def _news_payload_source(self, snapshot: _StreamSnapshot | None) -> dict[str, Any] | None:
        if snapshot is not None:
            return snapshot.news if isinstance(snapshot.news, dict) else None
        return _read_json_file(_NEWS_CACHE)

    def _get_memory(self):
        from autonomous_xauusd.memory_layer import MemoryLayer
        from backend.core.config import get_settings

        settings = get_settings()
        if self._memory is None or self._memory_database_url != settings.database_url:
            self._memory = MemoryLayer(settings.database_url)
            self._memory_database_url = settings.database_url
        return self._memory

    def _load_runtime_state(self, key: str) -> dict[str, Any] | None:
        memory = self._get_memory()
        state = memory.get_runtime_state(key)
        return state if isinstance(state, dict) else None

    def _load_model_history(self):
        memory = self._get_memory()
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
    return _read_json_file(_BOT_STATE)


def _read_json_file(path: Path) -> dict[str, Any] | None:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return None


_stream_service = WsStreamService()


def get_stream_service() -> WsStreamService:
    return _stream_service
