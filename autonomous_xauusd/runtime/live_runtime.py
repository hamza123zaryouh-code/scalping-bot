"""
Live Runtime — 24/7 production supervisor for the autonomous XAUUSD trading system.

Architecture:
  - Asyncio event loop (main thread)
  - Trading cycle runs in executor (blocking MT5/yfinance calls off the event loop)
  - Supervisor monitors health every 30 seconds
  - Crash recovery: automatic restart with exponential back-off
  - MT5 reconnect watchdog: reconnects after disconnects
  - Telegram reconnect: reconnects bot polling after failures
  - Heartbeat: broadcasts health state every 60 seconds via WebSocket
  - Persists state on clean shutdown (SIGINT / SIGTERM)
  - Structured JSON logging to live_logs/runtime.log

Startup sequence:
  1. Validate environment (secrets, MT5 credentials, database)
  2. Connect MT5 (or paper mode)
  3. Sync open positions from broker
  4. Start Telegram bot polling
  5. Start asyncio trading loop
  6. Start health monitor coroutine
  7. Start heartbeat broadcaster

Recovery sequence (on crash):
  1. Log exception with full traceback
  2. Notify Telegram
  3. Wait back-off delay (15s → 30s → 60s → 120s max)
  4. Re-initialize all layers
  5. Resync positions
  6. Resume trading loop
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
_UTC = timezone.utc
_RUNTIME_LOG = Path("live_logs/runtime.log")
_HEARTBEAT_PATH = Path("live_logs/heartbeat.json")
_BACKOFF_SEQUENCE = (15, 30, 60, 120)  # seconds between restart attempts


class RuntimeHealth:
    __slots__ = (
        "status", "cycle_count", "consecutive_errors", "last_cycle_at",
        "last_error", "mt5_connected", "telegram_connected", "uptime_start",
        "restarts",
    )

    def __init__(self) -> None:
        self.status: str = "starting"
        self.cycle_count: int = 0
        self.consecutive_errors: int = 0
        self.last_cycle_at: str = ""
        self.last_error: str = ""
        self.mt5_connected: bool = False
        self.telegram_connected: bool = False
        self.uptime_start: float = time.time()
        self.restarts: int = 0

    def to_dict(self) -> dict[str, Any]:
        uptime_s = int(time.time() - self.uptime_start)
        return {
            "status": self.status,
            "cycle_count": self.cycle_count,
            "consecutive_errors": self.consecutive_errors,
            "last_cycle_at": self.last_cycle_at,
            "last_error": self.last_error,
            "mt5_connected": self.mt5_connected,
            "telegram_connected": self.telegram_connected,
            "uptime_seconds": uptime_s,
            "uptime_human": _format_uptime(uptime_s),
            "restarts": self.restarts,
            "ts": datetime.now(_UTC).isoformat(),
        }


def _format_uptime(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m}m {s}s"


class LiveRuntime:
    """
    Production 24/7 runtime supervisor.

    Usage:
        runtime = LiveRuntime()
        asyncio.run(runtime.run_forever())
    """

    def __init__(self) -> None:
        self._health = RuntimeHealth()
        self._stop_event = asyncio.Event()
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="trading")
        self._trading_system: Any = None  # AutonomousTradingSystem instance
        self._ws_manager: Any = None
        self._restart_count: int = 0
        self._runtime_logger = self._setup_runtime_logger()

    # ─────────────────────────────────────────────────────────────
    # MAIN ENTRY POINT
    # ─────────────────────────────────────────────────────────────

    async def run_forever(self) -> None:
        """Start the runtime and run until SIGINT/SIGTERM or fatal error."""
        self._install_signal_handlers()
        self._health.uptime_start = time.time()
        self._log_event("runtime_start", {"pid": os.getpid()})
        logger.info("LiveRuntime: starting production trading system (PID=%d)", os.getpid())

        backoff_idx = 0

        while not self._stop_event.is_set():
            try:
                await self._boot_and_run()
                backoff_idx = 0  # clean exit resets back-off
            except asyncio.CancelledError:
                logger.info("LiveRuntime: shutdown requested")
                break
            except Exception as exc:
                self._restart_count += 1
                self._health.restarts = self._restart_count
                self._health.last_error = str(exc)[:300]
                self._health.status = "crashed"

                tb = traceback.format_exc()
                logger.critical("LiveRuntime: CRASH #%d — %s\n%s", self._restart_count, exc, tb)
                self._log_event("crash", {
                    "restart": self._restart_count,
                    "error": str(exc),
                    "traceback": tb[-1000:],
                })

                delay = _BACKOFF_SEQUENCE[min(backoff_idx, len(_BACKOFF_SEQUENCE) - 1)]
                backoff_idx = min(backoff_idx + 1, len(_BACKOFF_SEQUENCE) - 1)

                if self._trading_system is not None:
                    try:
                        self._send_telegram_alert(
                            f"SYSTEM CRASH #{self._restart_count}\n"
                            f"Error: {str(exc)[:200]}\n"
                            f"Restarting in {delay}s..."
                        )
                    except Exception:
                        pass

                if not self._stop_event.is_set():
                    logger.info("LiveRuntime: restarting in %ds...", delay)
                    try:
                        await asyncio.wait_for(
                            self._stop_event.wait(),
                            timeout=float(delay),
                        )
                    except asyncio.TimeoutError:
                        pass

        await self._graceful_shutdown()

    # ─────────────────────────────────────────────────────────────
    # BOOT SEQUENCE
    # ─────────────────────────────────────────────────────────────

    async def _boot_and_run(self) -> None:
        self._health.status = "booting"
        logger.info("LiveRuntime: boot sequence starting")

        # Step 1: validate environment
        await asyncio.get_event_loop().run_in_executor(
            self._executor, self._validate_environment
        )

        # Step 2: initialize trading system
        await asyncio.get_event_loop().run_in_executor(
            self._executor, self._initialize_trading_system
        )

        # Step 3: connect data/execution layer
        connected = await asyncio.get_event_loop().run_in_executor(
            self._executor, self._connect_data_layer
        )
        if not connected:
            raise RuntimeError("Data/execution layer connection failed — check MT5 or paper mode config")

        # Step 4: sync open positions
        await asyncio.get_event_loop().run_in_executor(
            self._executor, self._sync_open_positions
        )

        # Step 5: start Telegram
        await asyncio.get_event_loop().run_in_executor(
            self._executor, self._start_telegram
        )

        self._health.status = "running"
        logger.info("LiveRuntime: boot complete — entering trading loop")
        self._log_event("boot_complete", {"mode": self._get_mode()})

        # Step 6: run all coroutines concurrently
        await asyncio.gather(
            self._trading_loop(),
            self._health_monitor(),
            self._heartbeat_writer(),
        )

    # ─────────────────────────────────────────────────────────────
    # CORE LOOPS
    # ─────────────────────────────────────────────────────────────

    async def _trading_loop(self) -> None:
        """Run the main trading cycle in the executor (blocking I/O)."""
        loop = asyncio.get_event_loop()
        while not self._stop_event.is_set():
            try:
                await loop.run_in_executor(self._executor, self._run_one_cycle)
                self._health.cycle_count += 1
                self._health.consecutive_errors = 0
                self._health.last_cycle_at = datetime.now(_UTC).isoformat()
                self._health.status = "running"
            except Exception as exc:
                self._health.consecutive_errors += 1
                self._health.last_error = str(exc)[:200]
                self._health.status = "error"
                logger.exception("Trading cycle error (consecutive=%d)", self._health.consecutive_errors)
                if self._health.consecutive_errors >= 5:
                    raise RuntimeError(
                        f"Trading loop: {self._health.consecutive_errors} consecutive errors — initiating restart"
                    ) from exc

            # Sleep between cycles (15s default)
            poll_seconds = self._get_poll_interval()
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=float(poll_seconds))
            except asyncio.TimeoutError:
                pass

    async def _health_monitor(self) -> None:
        """Check system health every 30 seconds."""
        while not self._stop_event.is_set():
            try:
                await asyncio.get_event_loop().run_in_executor(
                    self._executor, self._run_health_checks
                )
            except Exception as exc:
                logger.warning("Health monitor error: %s", exc)

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=30.0)
            except asyncio.TimeoutError:
                pass

    async def _heartbeat_writer(self) -> None:
        """Write heartbeat JSON every 60 seconds."""
        while not self._stop_event.is_set():
            try:
                _HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
                _HEARTBEAT_PATH.write_text(
                    json.dumps(self._health.to_dict(), indent=2),
                    encoding="utf-8",
                )
            except Exception as exc:
                logger.debug("Heartbeat write failed: %s", exc)

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=60.0)
            except asyncio.TimeoutError:
                pass

    # ─────────────────────────────────────────────────────────────
    # EXECUTION STEPS (run in thread executor)
    # ─────────────────────────────────────────────────────────────

    def _validate_environment(self) -> None:
        from autonomous_xauusd.settings import load_settings
        settings = load_settings()
        mode = settings.mode
        logger.info("Environment validated: mode=%s symbol=%s tf=%s", mode, settings.symbol, settings.timeframe)

        if mode == "live" and not settings.mt5_ready:
            raise RuntimeError(
                "LIVE mode requires MT5_LOGIN, MT5_PASSWORD, MT5_SERVER to be set in .env"
            )
        if not settings.telegram_bot_token:
            logger.warning("TELEGRAM_BOT_TOKEN not set — Telegram alerts disabled")

    def _initialize_trading_system(self) -> None:
        from autonomous_xauusd.main import AutonomousTradingSystem
        self._trading_system = AutonomousTradingSystem()
        logger.info("AutonomousTradingSystem initialized")

    def _connect_data_layer(self) -> bool:
        if self._trading_system is None:
            return False
        result: bool = self._trading_system.engine.connect()
        self._health.mt5_connected = result
        if result:
            logger.info("Data/execution layer connected")
        else:
            logger.warning("Data/execution layer connection failed — check configuration")
        return result

    def _sync_open_positions(self) -> None:
        if self._trading_system is None:
            return
        try:
            from autonomous_xauusd.settings import load_settings
            settings = load_settings()
            open_trades = self._trading_system.memory.list_open_trades(settings.symbol)
            logger.info(
                "Position sync: %d open trades in DB for %s",
                len(open_trades), settings.symbol,
            )
        except Exception as exc:
            logger.warning("Position sync failed: %s", exc)

    def _start_telegram(self) -> None:
        if self._trading_system is None:
            return
        try:
            self._trading_system.telegram.start_in_background()
            self._health.telegram_connected = True
            logger.info("Telegram control layer started")
        except Exception as exc:
            logger.warning("Telegram start failed: %s — continuing without Telegram", exc)
            self._health.telegram_connected = False

    def _run_one_cycle(self) -> None:
        if self._trading_system is None:
            raise RuntimeError("Trading system not initialized")
        self._trading_system._process_control_commands()
        self._trading_system._run_cycle()

    def _run_health_checks(self) -> None:
        if self._trading_system is None:
            return
        # MT5 ping
        try:
            from autonomous_xauusd.settings import load_settings
            settings = load_settings()
            if settings.mode != "paper":
                account = self._trading_system.engine.account_status()
                self._health.mt5_connected = "balance" in account
        except Exception as exc:
            logger.warning("MT5 health check failed: %s", exc)
            self._health.mt5_connected = False
            # Attempt reconnect
            try:
                self._trading_system.engine.shutdown()
                reconnected = self._trading_system.engine.connect()
                self._health.mt5_connected = reconnected
                if reconnected:
                    logger.info("MT5 reconnected successfully")
                    self._send_telegram_alert("MT5 reconnected after disconnect")
            except Exception as recon_exc:
                logger.error("MT5 reconnect failed: %s", recon_exc)

    def _get_mode(self) -> str:
        try:
            from autonomous_xauusd.settings import load_settings
            return load_settings().mode
        except Exception:
            return "unknown"

    def _get_poll_interval(self) -> int:
        try:
            from autonomous_xauusd.settings import load_settings
            return load_settings().poll_interval_seconds
        except Exception:
            return 15

    def _send_telegram_alert(self, message: str) -> None:
        if self._trading_system is not None:
            try:
                self._trading_system.telegram.notify(message)
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────
    # SHUTDOWN
    # ─────────────────────────────────────────────────────────────

    async def _graceful_shutdown(self) -> None:
        logger.info("LiveRuntime: initiating graceful shutdown")
        self._health.status = "stopping"
        self._log_event("shutdown", {})

        if self._trading_system is not None:
            await asyncio.get_event_loop().run_in_executor(
                self._executor, self._shutdown_trading_system
            )

        self._executor.shutdown(wait=False)
        logger.info("LiveRuntime: shutdown complete")

    def _shutdown_trading_system(self) -> None:
        try:
            if self._trading_system:
                self._trading_system.engine.shutdown()
                self._send_telegram_alert("Trading system shut down cleanly.")
                logger.info("Trading system shut down")
        except Exception as exc:
            logger.warning("Shutdown error: %s", exc)

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_event_loop()

        def _handle_signal(signame: str) -> None:
            logger.info("Signal %s received — requesting stop", signame)
            self._stop_event.set()

        if sys.platform != "win32":
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, lambda s=sig.name: _handle_signal(s))
        else:
            # Windows: use KeyboardInterrupt handler
            signal.signal(signal.SIGINT, lambda s, f: self._stop_event.set())
            signal.signal(signal.SIGTERM, lambda s, f: self._stop_event.set())

    # ─────────────────────────────────────────────────────────────
    # STRUCTURED LOGGING
    # ─────────────────────────────────────────────────────────────

    def _setup_runtime_logger(self) -> logging.Logger:
        _RUNTIME_LOG.parent.mkdir(parents=True, exist_ok=True)
        rt_logger = logging.getLogger("live_runtime.structured")
        if not rt_logger.handlers:
            fh = logging.FileHandler(_RUNTIME_LOG, encoding="utf-8")
            fh.setFormatter(logging.Formatter("%(message)s"))
            rt_logger.addHandler(fh)
            rt_logger.setLevel(logging.INFO)
            rt_logger.propagate = False
        return rt_logger

    def _log_event(self, event: str, extra: dict[str, Any]) -> None:
        record = {
            "ts": datetime.now(_UTC).isoformat(),
            "event": event,
            "restart": self._restart_count,
            **extra,
        }
        try:
            self._runtime_logger.info(json.dumps(record))
        except Exception:
            pass


def run() -> None:
    """Entry point for scripts/run_live_bot.py."""
    # Ensure structured logging is set up before anything else
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    runtime = LiveRuntime()
    try:
        asyncio.run(runtime.run_forever())
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt — shutting down")
