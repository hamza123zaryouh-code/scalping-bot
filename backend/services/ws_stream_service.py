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

    def start(self) -> None:
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

    async def _stream_loop(self) -> None:
        tick = 0
        while self._running:
            try:
                await self._push_heartbeat()

                if tick % 3 == 0:   # every 15s
                    await self._push_equity()

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

    async def _push_equity(self) -> None:
        try:
            from backend.websocket.manager import ws_manager
            state = _read_bot_state()
            if state is None:
                return
            balance = float(state.get("balance", 0.0))
            equity = float(state.get("equity", 0.0))
            start_eq = float(state.get("day_start_equity", balance))
            dd_pct = ((start_eq - equity) / start_eq * 100) if start_eq > 0 else 0.0
            await ws_manager.push_equity_update(
                equity=equity,
                balance=balance,
                drawdown_pct=max(0.0, dd_pct),
            )
        except Exception as exc:
            logger.debug("_push_equity: %s", exc)

    async def _push_sentiment(self) -> None:
        try:
            from backend.websocket.manager import ws_manager
            state = _read_bot_state()
            if state is None:
                return
            sentiment = state.get("last_sentiment")
            if sentiment:
                await ws_manager.push_sentiment(sentiment)
        except Exception as exc:
            logger.debug("_push_sentiment: %s", exc)

    async def _push_risk(self) -> None:
        try:
            from backend.websocket.manager import ws_manager
            from backend.core.config import get_settings
            settings = get_settings()
            from autonomous_xauusd.memory_layer import MemoryLayer
            memory = MemoryLayer(settings.database_url)
            cb = memory.get_runtime_state("circuit_breaker") or {}
            state = _read_bot_state()
            equity = float((state or {}).get("equity", 160000.0))
            start_eq = float((state or {}).get("day_start_equity", equity))
            risk_payload = {
                "circuit_breaker_active": cb.get("circuit_breaker_active", False),
                "risk_multiplier": cb.get("risk_multiplier", 1.0),
                "daily_loss": round(max(0.0, start_eq - equity), 2),
                "daily_loss_pct": round(max(0.0, (start_eq - equity) / start_eq * 100) if start_eq > 0 else 0.0, 2),
                "can_trade": not cb.get("circuit_breaker_active", False),
            }
            await ws_manager.push_risk(risk_payload)
        except Exception as exc:
            logger.debug("_push_risk: %s", exc)

    async def _push_regime(self) -> None:
        try:
            from backend.websocket.manager import ws_manager
            from backend.core.config import get_settings
            settings = get_settings()
            from autonomous_xauusd.memory_layer import MemoryLayer
            memory = MemoryLayer(settings.database_url)
            engine_state = memory.get_runtime_state("engine_status") or {}
            regime = {
                "session": engine_state.get("session", "unknown"),
                "status": engine_state.get("status", "unknown"),
                "last_signal": engine_state.get("last_signal", ""),
            }
            await ws_manager.push_regime(regime)
        except Exception as exc:
            logger.debug("_push_regime: %s", exc)

    async def _push_news(self) -> None:
        try:
            from backend.websocket.manager import ws_manager
            news_cache = Path("live_logs/news_cache.json")
            if not news_cache.exists():
                return
            import json
            data = json.loads(news_cache.read_text(encoding="utf-8"))
            await ws_manager.push_news({
                "composite_sentiment": data.get("composite_sentiment", 0.0),
                "danger_score": data.get("danger_score", 0.0),
                "high_impact_count": data.get("high_impact_count", 0),
                "total_headlines": data.get("total_headlines", 0),
                "top_keywords": data.get("top_keywords", [])[:6],
                "should_pause": data.get("should_pause_trading", False),
            })
        except Exception as exc:
            logger.debug("_push_news: %s", exc)

    async def _push_heartbeat(self) -> None:
        try:
            from backend.websocket.manager import ws_manager
            if _HEARTBEAT.exists():
                import json
                data = json.loads(_HEARTBEAT.read_text(encoding="utf-8"))
                await ws_manager.push_heartbeat(data)
            else:
                await ws_manager.push_heartbeat({
                    "status": "api_only",
                    "ts": datetime.now(_UTC).isoformat(),
                    "trading_bot_running": False,
                })
        except Exception as exc:
            logger.debug("_push_heartbeat: %s", exc)

    async def _push_ml(self) -> None:
        try:
            from backend.websocket.manager import ws_manager
            from backend.core.config import get_settings
            settings = get_settings()
            from autonomous_xauusd.memory_layer import MemoryLayer
            memory = MemoryLayer(settings.database_url)
            model_hist = memory.model_history()
            if model_hist:
                latest = model_hist[-1]
                await ws_manager.push_ml_update({
                    "accuracy": latest.get("accuracy", 0.0),
                    "f1_score": latest.get("f1_score", 0.0),
                    "sample_count": latest.get("sample_count", 0),
                    "trained_at": latest.get("trained_at", ""),
                })
        except Exception as exc:
            logger.debug("_push_ml: %s", exc)


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
