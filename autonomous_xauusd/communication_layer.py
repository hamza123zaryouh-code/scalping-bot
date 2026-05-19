from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx

from autonomous_xauusd.memory_layer import MemoryLayer
from autonomous_xauusd.settings import load_settings

# Lazy-imported at runtime to avoid circular dependencies
_TelegramService: Any = None


def _get_telegram_service_class() -> Any:
    global _TelegramService
    if _TelegramService is None:
        from backend.services.telegram_service import TelegramService  # noqa: PLC0415
        _TelegramService = TelegramService
    return _TelegramService

_MAX_TG_LEN = 4000
_TRUNCATED_SUFFIX = "\n…(ingekort)"


def _truncate(text: str) -> str:
    if len(text) <= _MAX_TG_LEN:
        return text
    return text[: _MAX_TG_LEN - len(_TRUNCATED_SUFFIX)] + _TRUNCATED_SUFFIX


try:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
    from telegram.error import Conflict, TelegramError
    from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

    TELEGRAM_AVAILABLE = True
except ImportError:  # pragma: no cover
    Conflict = TelegramError = Exception  # type: ignore[assignment]
    Update = Any  # type: ignore[assignment]
    Application = None  # type: ignore[assignment]
    CallbackQueryHandler = None  # type: ignore[assignment]
    CommandHandler = None  # type: ignore[assignment]
    ContextTypes = Any  # type: ignore[assignment]
    InlineKeyboardButton = InlineKeyboardMarkup = Any  # type: ignore[assignment]
    TELEGRAM_AVAILABLE = False


logger = logging.getLogger(__name__)


class _RequiresConfirmation(Exception):
    """Raised by _dispatch_control when the action needs user confirmation."""
    def __init__(self, action: str) -> None:
        self.action = action


class TelegramBackendClient:
    def __init__(self, api_key: str, base_url: str, telegram_user_id: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.telegram_user_id = telegram_user_id
        self.available = bool(base_url)

    async def get(self, path: str) -> dict[str, Any]:
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "X-API-Key": self.api_key,
                "X-Telegram-User-Id": self.telegram_user_id,
            },
            timeout=120.0,
        ) as client:
            response = await client.get(path)
            response.raise_for_status()
            return response.json()

    async def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "X-API-Key": self.api_key,
                "X-Telegram-User-Id": self.telegram_user_id,
            },
            timeout=120.0,
        ) as client:
            response = await client.post(path, json=payload)
            response.raise_for_status()
            return response.json()


class TelegramControlLayer:
    def __init__(
        self,
        token: str,
        chat_id: str,
        owner_user_id: str,
        backend_api_key: str,
        backend_base_url: str,
        status_callback: Callable[[], str],
        stop_callback: Callable[[], str],
        train_callback: Callable[[], str],
        ping_callback: Callable[[], str] | None = None,
        logs_callback: Callable[[], str] | None = None,
        heat_callback: Callable[[], str] | None = None,
        restart_callback: Callable[[], str] | None = None,
    ) -> None:
        self.token = token
        self.chat_id = chat_id
        self.owner_user_id = owner_user_id.strip()
        self.status_callback = status_callback
        self.stop_callback = stop_callback
        self.train_callback = train_callback
        self.ping_callback = ping_callback
        self.logs_callback = logs_callback
        self.heat_callback = heat_callback
        self.restart_callback = restart_callback
        self.enabled = bool(token and chat_id and TELEGRAM_AVAILABLE)
        self._thread: threading.Thread | None = None
        self._thread_lock = threading.Lock()
        self._polling_stop = threading.Event()
        self._polling_conflict = threading.Event()
        self._callback_last_time: dict[str, float] = {}
        self._backend_warn_at: dict[str, float] = {}  # path -> last warning time
        self._unauthorized_warn_at: dict[str, float] = {}  # user_id -> last warning time
        self._backend = TelegramBackendClient(
            api_key=backend_api_key,
            base_url=backend_base_url,
            telegram_user_id=self.owner_user_id,
        )
        self._memory = MemoryLayer(load_settings().database_url)
        self._memory.initialize()

        # Embedded local service — makes all buttons work without a separate backend process
        self._service: Any = None
        try:
            svc_cls = _get_telegram_service_class()
            self._service = svc_cls()
            logger.info("TelegramControlLayer: embedded service actief — backend HTTP niet nodig")
        except Exception as exc:
            logger.warning(
                "TelegramControlLayer: embedded service kon niet starten (%s); "
                "knoppen vallen terug op HTTP backend",
                exc,
            )

        if token and chat_id and not TELEGRAM_AVAILABLE:
            logger.warning("python-telegram-bot is not installed; Telegram control layer is disabled.")

    def start_in_background(self) -> None:
        if not self.enabled:
            return

        with self._thread_lock:
            if self._thread is not None and self._thread.is_alive():
                return

            self._polling_stop.clear()
            self._polling_conflict.clear()
            self._thread = threading.Thread(target=self._run_polling, name="telegram-control", daemon=True)
            self._thread.start()

    def notify(self, message: str) -> bool:
        if not self.enabled:
            return False

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": _truncate(message)}
        delays = (0, 3, 8)  # immediate, then 3s, then 8s
        for attempt, delay in enumerate(delays):
            if delay:
                time.sleep(delay)
            try:
                httpx.post(url, json=payload, timeout=30.0).raise_for_status()
                return True
            except Exception as exc:  # pragma: no cover - network dependent
                if attempt == len(delays) - 1:
                    logger.warning("Telegram notification failed after %d attempts: %s", len(delays), exc)
                else:
                    logger.debug("Telegram notify attempt %d failed, retrying: %s", attempt + 1, exc)
        return False

    def _run_polling(self) -> None:
        try:
            asyncio.run(self._run_application())
        except Conflict:
            logger.warning("Telegram polling disabled because another bot instance is already consuming updates.")
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Telegram polling stopped: %s", exc)
        finally:
            with self._thread_lock:
                self._thread = None

    async def _run_application(self) -> None:
        if Application is None or CommandHandler is None or CallbackQueryHandler is None:
            return

        application = Application.builder().token(self.token).build()
        application.add_handler(CommandHandler("start", self._on_start))
        application.add_handler(CommandHandler("menu", self._on_start))
        application.add_handler(CommandHandler("status", self._on_status))
        application.add_handler(CommandHandler("ping", self._on_ping))
        application.add_handler(CommandHandler("logs", self._on_logs))
        application.add_handler(CommandHandler("heat", self._on_heat))
        application.add_handler(CommandHandler("restart", self._on_restart))
        application.add_handler(CommandHandler("systeem", self._on_systeem))
        application.add_handler(CommandHandler("help", self._on_help))
        application.add_handler(CallbackQueryHandler(self._on_callback))

        await application.initialize()
        try:
            await application.start()
            await application.updater.start_polling(
                drop_pending_updates=True,
                bootstrap_retries=0,
                error_callback=self._handle_polling_error,
            )
            while not self._polling_stop.is_set() and not self._polling_conflict.is_set():
                await asyncio.sleep(1)
        finally:
            if getattr(application, "updater", None) and application.updater.running:
                await application.updater.stop()
            if application.running:
                await application.stop()
            await application.shutdown()

    def _handle_polling_error(self, error: TelegramError) -> None:
        if isinstance(error, Conflict):
            if not self._polling_conflict.is_set():
                logger.warning("Telegram polling conflict detected; stopping local poller so logs stay clean.")
            self._polling_conflict.set()
            return

        logger.warning("Telegram polling error: %s", error)

    async def _on_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:  # noqa: ARG002
        if not self._is_authorized(update):
            await self._deny_access(update, "menu_open")
            return

        self._log_user_action(update, "menu_open", "success", {"screen": "main"})
        if update.effective_message:
            await update.effective_message.reply_text(
                self._main_menu_text(),
                reply_markup=self._main_menu_keyboard(),
            )

    def _should_warn_backend(self, key: str, interval: float = 300.0) -> bool:
        now = time.monotonic()
        if now - self._backend_warn_at.get(key, 0.0) >= interval:
            self._backend_warn_at[key] = now
            return True
        return False

    # ── Lokale service router (geen HTTP vereist) ─────────────────────────────

    def _local_get(self, path: str) -> dict[str, Any]:
        """Routeer GET pad naar embedded TelegramService methode."""
        svc = self._service
        if svc is None:
            raise RuntimeError("Embedded service niet beschikbaar")
        route = path.split("?")[0].rstrip("/")
        if not route.startswith("/api/v1/telegram/"):
            raise ValueError(f"Onbekend pad: {path}")
        seg = route[len("/api/v1/telegram/"):]

        if seg == "status":
            return {"data": svc.get_status_overview()}
        if seg.startswith("risk/"):
            return {"data": svc.get_risk_status(seg[5:])}
        if seg.startswith("signals/"):
            return {"data": svc.get_signal_snapshot(seg[8:])}
        if seg == "backtest/latest":
            return {"data": svc.get_latest_backtest_result()}
        if seg == "backtest/compare":
            return {"data": svc.compare_strategy_versions()}
        if seg == "backtest/equity-curve-summary":
            return {"data": svc.get_equity_curve_summary()}
        if seg.startswith("memory/"):
            return {"data": svc.get_memory_snapshot(seg[7:])}
        if seg.startswith("reports/"):
            return {"data": svc.build_report_snapshot(seg[8:])}
        raise ValueError(f"Geen lokale handler voor GET {path}")

    def _local_post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Routeer POST pad naar embedded TelegramService methode."""
        svc = self._service
        if svc is None:
            raise RuntimeError("Embedded service niet beschikbaar")
        route = path.split("?")[0].rstrip("/")
        if not route.startswith("/api/v1/telegram/"):
            raise ValueError(f"Onbekend pad: {path}")
        seg = route[len("/api/v1/telegram/"):]

        user_id = str(payload.get("telegram_user_id", self.owner_user_id) or self.owner_user_id)
        username = payload.get("telegram_username")
        confirmed = bool(payload.get("confirmed", False))

        if seg.startswith("control/"):
            action = seg[8:]
            return {"data": svc.handle_control_action(action, user_id, username, confirmed)}
        if seg == "signals/toggle":
            return {"data": svc.toggle_signals(bool(payload.get("enabled", True)), user_id, username)}
        if seg == "backtest/quick-run":
            return {"data": svc.run_quick_backtest(user_id, username)}
        if seg == "memory/train":
            return {"data": svc.handle_control_action("train_ai", user_id, username, confirmed=True)}
        if seg == "reports/export-trade-log":
            return {"data": svc.export_trade_log(user_id, username)}
        raise ValueError(f"Geen lokale handler voor POST {path}")

    # ── Backend GET / POST met lokale service als primaire bron ──────────────

    async def _backend_get(self, path: str, fallback_text: str | None = None) -> dict[str, Any]:
        """GET via embedded service (primair) of HTTP backend (fallback)."""
        if self._service is not None:
            try:
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(None, self._local_get, path)
            except Exception as exc:
                logger.warning("Embedded service GET %s mislukt: %s", path, exc)

        # HTTP backend fallback
        try:
            return await self._backend.get(path)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            if self._should_warn_backend(f"GET:{path}"):
                logger.warning("Backend GET %s unavailable (%s); using fallback", path, exc)
            text = fallback_text or "Backend tijdelijk niet beschikbaar. Probeer opnieuw."
            return {"data": {"summary": text}}

    async def _backend_post(
        self, path: str, payload: dict[str, Any], fallback_text: str | None = None
    ) -> dict[str, Any]:
        """POST via embedded service (primair) of HTTP backend (fallback)."""
        if self._service is not None:
            try:
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(None, self._local_post, path, payload)
            except Exception as exc:
                logger.warning("Embedded service POST %s mislukt: %s", path, exc)

        # HTTP backend fallback
        try:
            return await self._backend.post(path, payload)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            if self._should_warn_backend(f"POST:{path}"):
                logger.warning("Backend POST %s unavailable (%s); using fallback", path, exc)
            text = fallback_text or "Backend tijdelijk niet beschikbaar. Probeer opnieuw."
            return {"data": {"summary": text, "requires_confirmation": False, "status": "error", "command_id": None}}

    async def _on_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:  # noqa: ARG002
        if not self._is_authorized(update):
            await self._deny_access(update, "command_status")
            return

        self._log_user_action(update, "command_status", "success", {})
        fallback = self.status_callback() if self.status_callback else None
        response = await self._backend_get("/api/v1/telegram/status", fallback_text=fallback)
        summary = response["data"]["summary"]
        if update.effective_message:
            await update.effective_message.reply_text(_truncate(summary), reply_markup=self._dashboard_keyboard())

    async def _on_ping(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:  # noqa: ARG002
        if not self._is_authorized(update):
            await self._deny_access(update, "ping")
            return
        self._log_user_action(update, "ping", "success", {})
        text = self.ping_callback() if self.ping_callback else "PONG — Bot actief"
        if update.effective_message:
            await update.effective_message.reply_text(_truncate(text))

    async def _on_logs(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:  # noqa: ARG002
        if not self._is_authorized(update):
            await self._deny_access(update, "logs")
            return
        self._log_user_action(update, "logs", "success", {})
        text = self.logs_callback() if self.logs_callback else "Logs callback niet geconfigureerd."
        if update.effective_message:
            await update.effective_message.reply_text(_truncate(text))

    async def _on_heat(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:  # noqa: ARG002
        if not self._is_authorized(update):
            await self._deny_access(update, "heat")
            return
        self._log_user_action(update, "heat", "success", {})
        text = self.heat_callback() if self.heat_callback else "Heat callback niet geconfigureerd."
        if update.effective_message:
            await update.effective_message.reply_text(_truncate(text))

    async def _on_restart(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:  # noqa: ARG002
        if not self._is_authorized(update):
            await self._deny_access(update, "restart")
            return
        self._log_user_action(update, "restart", "pending_confirm", {})
        if update.effective_message:
            await update.effective_message.reply_text(
                "Weet je zeker dat je de bot wilt herstarten?\n"
                "Bot stopt (exit code 1) en wordt automatisch herstart door vps_startup.bat.",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("JA, herstart", callback_data="confirm:restart_bot:yes"),
                        InlineKeyboardButton("Annuleer", callback_data="confirm:restart_bot:no"),
                    ]
                ]),
            )

    async def _on_systeem(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:  # noqa: ARG002
        if not self._is_authorized(update):
            await self._deny_access(update, "systeem")
            return
        self._log_user_action(update, "systeem_menu", "success", {})
        if update.effective_message:
            await update.effective_message.reply_text(
                "Systeem beheer — kies een actie:",
                reply_markup=self._systeem_keyboard(),
            )

    async def _on_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:  # noqa: ARG002
        if not self._is_authorized(update):
            await self._deny_access(update, "help")
            return
        help_text = (
            "XAUUSD Bot — Beschikbare commando's\n"
            "\n"
            "BASICS\n"
            "  /start of /menu — Hoofdmenu openen\n"
            "  /status        — Bot status overzicht\n"
            "  /ping          — Controleer of bot actief is\n"
            "\n"
            "SYSTEEM\n"
            "  /logs          — Laatste 40 regels logbestand\n"
            "  /heat          — Portfolio heat (open risico%)\n"
            "  /restart       — Bot herstarten via watchdog\n"
            "  /systeem       — Systeem menu\n"
            "\n"
            "MENU SECTIES (via /menu knoppen)\n"
            "  Dashboard      — Equity, PnL, FTMO status\n"
            "  Bot Control    — Start/Stop/Pause/Resume\n"
            "  Risk Control   — FTMO regels, drawdown\n"
            "  Signals        — Laatste signalen\n"
            "  AI Memory      — ML model trainen\n"
            "  Backtest       — Backtests uitvoeren\n"
            "  Reports        — Dag/week/maand rapporten\n"
        )
        if update.effective_message:
            await update.effective_message.reply_text(help_text, reply_markup=self._main_menu_keyboard())

    async def _on_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:  # noqa: ARG002
        query = update.callback_query
        if query is None:
            return

        if not self._is_authorized(update):
            await self._deny_access(update, query.data or "unknown", query=query)
            return

        user = update.effective_user
        user_id = str(user.id) if user else "unknown"
        now = time.monotonic()
        if now - self._callback_last_time.get(user_id, 0.0) < 1.0:
            await query.answer("Even geduld...", show_alert=False)
            return
        self._callback_last_time[user_id] = now

        data = query.data or ""
        try:
            if data == "menu:main":
                self._log_user_action(update, "menu_main", "success", {})
                await query.answer()
                await query.edit_message_text(self._main_menu_text(), reply_markup=self._main_menu_keyboard())
                return

            if data.startswith("menu:"):
                section = data.split(":", 1)[1]
                self._log_user_action(update, f"menu_{section}", "success", {})
                await query.answer()
                await query.edit_message_text(self._menu_text(section), reply_markup=self._menu_keyboard(section))
                return

            if data.startswith("confirm:"):
                await self._handle_confirmation(update, query, data)
                return

            await self._handle_action(update, query, data)
        except _RequiresConfirmation as exc:
            await query.answer("Bevestiging nodig")
            await query.edit_message_text(
                f"Weet je zeker dat je '{self._button_label(exc.action)}' wilt uitvoeren?",
                reply_markup=self._confirmation_keyboard(exc.action),
            )
        except httpx.HTTPStatusError as exc:
            logger.warning("Telegram backend HTTP error: %s", exc)
            self._log_user_action(update, data, "error", {"detail": str(exc)})
            await query.answer("Backend fout", show_alert=True)
            await query.edit_message_text(
                _truncate(f"Actie mislukt:\n{exc.response.text}"),
                reply_markup=self._main_menu_keyboard(),
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Telegram callback failed")
            self._log_user_action(update, data, "error", {"detail": str(exc)})
            await query.answer("Onverwachte fout", show_alert=True)
            await query.edit_message_text(
                _truncate(f"Onverwachte fout:\n{str(exc)}"),
                reply_markup=self._main_menu_keyboard(),
            )

    async def _handle_confirmation(self, update: Update, query, data: str) -> None:
        parts = data.split(":", 2)
        if len(parts) != 3:
            await query.answer("Ongeldige bevestiging", show_alert=True)
            return
        _, action, decision = parts
        if decision == "no":
            self._log_user_action(update, f"{action}_cancelled", "cancelled", {})
            await query.answer("Geannuleerd")
            await query.edit_message_text(
                "Actie geannuleerd.",
                reply_markup=self._menu_keyboard("control"),
            )
            return

        # Systeem herstart — lokaal afhandelen, geen backend nodig
        if action == "restart_bot":
            self._log_user_action(update, action, "confirmed", {})
            text = self.restart_callback() if self.restart_callback else "Herstart niet geconfigureerd."
            await query.answer("Bevestigd")
            await query.edit_message_text(_truncate(text), reply_markup=self._systeem_keyboard())
            return

        payload = self._identity_payload(update, confirmed=True)
        stop_fallback = (
            self.stop_callback() if action in ("emergency_stop", "stop_bot") and self.stop_callback else None
        )
        response = await self._backend_post(f"/api/v1/telegram/control/{action}", payload, fallback_text=stop_fallback)
        text = response["data"]["summary"]
        self._log_user_action(update, action, "confirmed", {"response": text})
        await query.answer("Bevestigd")
        await query.edit_message_text(_truncate(text), reply_markup=self._menu_keyboard("control"))

    async def _handle_action(self, update: Update, query, data: str) -> None:
        await query.answer()
        text, keyboard = await self._dispatch_action(update, data)
        self._log_user_action(update, data, "success", {"summary": text[:500]})
        try:
            await query.edit_message_text(_truncate(text), reply_markup=keyboard)
        except Exception as e:
            if "Message is not modified" not in str(e):
                raise

    async def _dispatch_action(self, update: Update, data: str) -> tuple[str, Any]:
        if data == "status:overview":
            fallback = self.status_callback() if self.status_callback else None
            response = await self._backend_get("/api/v1/telegram/status", fallback_text=fallback)
            return response["data"]["summary"], self._dashboard_keyboard()

        if data.startswith("status:"):
            fallback = self.status_callback() if self.status_callback else None
            response = await self._backend_get("/api/v1/telegram/status", fallback_text=fallback)
            return self._format_status_detail(data.split(":", 1)[1], response["data"]), self._dashboard_keyboard()

        if data.startswith("control:"):
            return await self._dispatch_control(update, data)

        if data.startswith("risk:"):
            section = data.split(":", 1)[1]
            response = await self._backend_get(f"/api/v1/telegram/risk/{section}")
            return response["data"]["summary"], self._menu_keyboard("risk")

        if data.startswith("signals_toggle:"):
            enabled = data.endswith(":on")
            response = await self._backend_post(
                "/api/v1/telegram/signals/toggle",
                {**self._identity_payload(update), "enabled": enabled},
            )
            return response["data"]["summary"], self._menu_keyboard("signals")

        if data.startswith("signals:"):
            section = data.split(":", 1)[1]
            response = await self._backend_get(f"/api/v1/telegram/signals/{section}")
            return response["data"]["summary"], self._menu_keyboard("signals")

        if data.startswith("backtest:"):
            return await self._dispatch_backtest(update, data)

        if data == "memory:train":
            train_fallback = self.train_callback() if self.train_callback else None
            response = await self._backend_post(
                "/api/v1/telegram/memory/train", self._identity_payload(update), fallback_text=train_fallback
            )
            return response["data"]["summary"], self._menu_keyboard("memory")

        if data.startswith("memory:"):
            section = data.split(":", 1)[1]
            response = await self._backend_get(f"/api/v1/telegram/memory/{section}")
            return response["data"]["summary"], self._menu_keyboard("memory")

        if data.startswith("reports:"):
            return await self._dispatch_reports(update, data)

        if data.startswith("systeem:"):
            return await self._dispatch_systeem(update, data)

        raise ValueError(f"Unsupported callback: {data}")

    async def _dispatch_control(self, update: Update, data: str) -> tuple[str, Any]:
        action = data.split(":", 1)[1]
        payload = self._identity_payload(update)
        stop_fallback = (
            self.stop_callback() if action in ("emergency_stop", "stop_bot") and self.stop_callback else None
        )
        response = await self._backend_post(
            f"/api/v1/telegram/control/{action}", payload, fallback_text=stop_fallback
        )
        result = response["data"]
        if result.get("requires_confirmation"):
            self._log_user_action(update, action, "confirmation_required", {})
            raise _RequiresConfirmation(action)
        return result["summary"], self._menu_keyboard("control")

    async def _dispatch_backtest(self, update: Update, data: str) -> tuple[str, Any]:
        backtest_routes: dict[str, tuple[str, str | None]] = {
            "backtest:quick_run": ("/api/v1/telegram/backtest/quick-run", "post"),
            "backtest:latest": ("/api/v1/telegram/backtest/latest", None),
            "backtest:compare": ("/api/v1/telegram/backtest/compare", None),
            "backtest:equity_curve": ("/api/v1/telegram/backtest/equity-curve-summary", None),
        }
        if data not in backtest_routes:
            raise ValueError(f"Unsupported backtest callback: {data}")
        path, method = backtest_routes[data]
        if method == "post":
            response = await self._backend_post(path, self._identity_payload(update))
        else:
            response = await self._backend_get(path)
        return response["data"]["summary"], self._menu_keyboard("backtest")

    async def _dispatch_systeem(self, update: Update, data: str) -> tuple[str, Any]:
        action = data.split(":", 1)[1]
        if action == "ping":
            text = self.ping_callback() if self.ping_callback else "PONG"
            return _truncate(text), self._systeem_keyboard()
        if action == "logs":
            text = self.logs_callback() if self.logs_callback else "Geen logs"
            return _truncate(text), self._systeem_keyboard()
        if action == "heat":
            text = self.heat_callback() if self.heat_callback else "Geen heat data"
            return _truncate(text), self._systeem_keyboard()
        if action == "restart":
            return (
                "Weet je zeker dat je de bot wilt herstarten?\n"
                "Bot stopt (exit code 1) en vps_startup.bat herstart automatisch.",
                InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("JA, herstart", callback_data="confirm:restart_bot:yes"),
                        InlineKeyboardButton("Annuleer", callback_data="confirm:restart_bot:no"),
                    ]
                ]),
            )
        raise ValueError(f"Unsupported systeem action: {action}")

    async def _dispatch_reports(self, update: Update, data: str) -> tuple[str, Any]:
        section = data.split(":", 1)[1]
        if section == "export_trade_log":
            response = await self._backend_post(
                "/api/v1/telegram/reports/export-trade-log",
                self._identity_payload(update),
            )
        else:
            response = await self._backend_get(f"/api/v1/telegram/reports/{section}")
        return response["data"]["summary"], self._menu_keyboard("reports")

    async def _deny_access(self, update: Update, action: str, query=None) -> None:
        self._log_user_action(update, action, "denied", {"owner_user_id": self.owner_user_id})
        if query is not None:
            await query.answer("Geen toegang", show_alert=True)
            return
        if update.effective_message:
            await update.effective_message.reply_text(
                "Geen toegang. Alleen de geconfigureerde owner kan deze bot bedienen."
            )

    def _is_authorized(self, update: Update) -> bool:
        if not self.owner_user_id:
            logger.warning("TELEGRAM_OWNER_USER_ID is not configured; Telegram controls are disabled.")
            return False
        user = update.effective_user
        if user is None:
            return False
        authorized = str(user.id) == self.owner_user_id
        if not authorized:
            uid = str(user.id)
            now = time.monotonic()
            if now - self._unauthorized_warn_at.get(uid, 0.0) >= 300.0:
                self._unauthorized_warn_at[uid] = now
                logger.warning("Unauthorized Telegram access attempt from user_id=%s", uid)
        return authorized

    def _identity_payload(self, update: Update, confirmed: bool = False) -> dict[str, Any]:
        user = update.effective_user
        return {
            "telegram_user_id": str(user.id) if user else "",
            "telegram_username": user.username if user else None,
            "confirmed": confirmed,
        }

    def _log_user_action(self, update: Update, action: str, status: str, details: dict[str, Any]) -> None:
        user = update.effective_user
        self._memory.log_telegram_action(
            telegram_user_id=str(user.id) if user else "unknown",
            telegram_username=user.username if user else None,
            action=action,
            status=status,
            details=details,
        )

    def _main_menu_text(self) -> str:
        return (
            "🤖 XAUUSD AI Trading Bot\n"
            "Realtime control interface voor trading, risk, signals, backtests en AI memory.\n\n"
            "Kies een module:"
        )

    def _menu_text(self, section: str) -> str:
        titles = {
            "dashboard": "📊 Dashboard",
            "control": "⚙️ Bot Control",
            "risk": "🛡 Risk Control",
            "signals": "📡 Signals",
            "memory": "🧠 AI Memory",
            "backtest": "🧪 Backtest",
            "reports": "📄 Reports",
            "systeem": "🖥 Systeem Beheer",
        }
        return f"{titles.get(section, 'Control')}\nKies een actie:"

    def _main_menu_keyboard(self):
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("📊 Dashboard", callback_data="menu:dashboard")],
                [InlineKeyboardButton("⚙️ Bot Control", callback_data="menu:control")],
                [InlineKeyboardButton("🛡 Risk Control", callback_data="menu:risk")],
                [InlineKeyboardButton("📡 Signals", callback_data="menu:signals")],
                [InlineKeyboardButton("🧠 AI Memory", callback_data="menu:memory")],
                [InlineKeyboardButton("🧪 Backtest", callback_data="menu:backtest")],
                [InlineKeyboardButton("📄 Reports", callback_data="menu:reports")],
                [InlineKeyboardButton("🖥 Systeem", callback_data="menu:systeem")],
            ]
        )

    def _dashboard_keyboard(self):
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Account Status", callback_data="status:account_status")],
                [
                    InlineKeyboardButton("Equity", callback_data="status:equity"),
                    InlineKeyboardButton("Balance", callback_data="status:balance"),
                ],
                [
                    InlineKeyboardButton("Open PnL", callback_data="status:open_pnl"),
                    InlineKeyboardButton("Daily PnL", callback_data="status:daily_pnl"),
                ],
                [
                    InlineKeyboardButton("Weekly PnL", callback_data="status:weekly_pnl"),
                    InlineKeyboardButton("Monthly PnL", callback_data="status:monthly_pnl"),
                ],
                [
                    InlineKeyboardButton("Drawdown", callback_data="status:drawdown"),
                    InlineKeyboardButton("FTMO Status", callback_data="status:ftmo_status"),
                ],
                [InlineKeyboardButton("Refresh Overview", callback_data="status:overview")],
                [InlineKeyboardButton("⬅️ Main Menu", callback_data="menu:main")],
            ]
        )

    def _control_keyboard(self):
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Start Bot", callback_data="control:start_bot"),
                    InlineKeyboardButton("Stop Bot", callback_data="control:stop_bot"),
                ],
                [
                    InlineKeyboardButton("Pause Trading", callback_data="control:pause_trading"),
                    InlineKeyboardButton("Resume Trading", callback_data="control:resume_trading"),
                ],
                [InlineKeyboardButton("Emergency Stop", callback_data="control:emergency_stop")],
                [InlineKeyboardButton("Close All Positions", callback_data="control:close_all_positions")],
                [InlineKeyboardButton("⬅️ Main Menu", callback_data="menu:main")],
            ]
        )

    def _risk_keyboard(self):
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Daily Risk Status", callback_data="risk:daily")],
                [InlineKeyboardButton("Weekly Risk Status", callback_data="risk:weekly")],
                [InlineKeyboardButton("Monthly Target Status", callback_data="risk:monthly_target")],
                [InlineKeyboardButton("Drawdown Check", callback_data="risk:drawdown")],
                [InlineKeyboardButton("Loss Streak Check", callback_data="risk:loss_streak")],
                [InlineKeyboardButton("FTMO Rules Check", callback_data="risk:ftmo_rules")],
                [InlineKeyboardButton("⬅️ Main Menu", callback_data="menu:main")],
            ]
        )

    def _signals_keyboard(self):
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Latest Signal", callback_data="signals:latest")],
                [InlineKeyboardButton("Signal Confidence", callback_data="signals:confidence")],
                [InlineKeyboardButton("Signals Today", callback_data="signals:today")],
                [InlineKeyboardButton("Enable Signals", callback_data="signals_toggle:state:on")],
                [InlineKeyboardButton("Disable Signals", callback_data="signals_toggle:state:off")],
                [InlineKeyboardButton("⬅️ Main Menu", callback_data="menu:main")],
            ]
        )

    def _backtest_keyboard(self):
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Run Quick Backtest", callback_data="backtest:quick_run")],
                [InlineKeyboardButton("Latest Backtest Result", callback_data="backtest:latest")],
                [InlineKeyboardButton("Compare Baseline vs Latest", callback_data="backtest:compare")],
                [InlineKeyboardButton("Show Equity Curve Summary", callback_data="backtest:equity_curve")],
                [InlineKeyboardButton("⬅️ Main Menu", callback_data="menu:main")],
            ]
        )

    def _memory_keyboard(self):
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Train AI", callback_data="memory:train")],
                [InlineKeyboardButton("Show Best Setups", callback_data="memory:best_setups")],
                [InlineKeyboardButton("Show Losing Setups", callback_data="memory:losing_setups")],
                [InlineKeyboardButton("Optimizer Status", callback_data="memory:optimizer_status")],
                [InlineKeyboardButton("Learning Progress", callback_data="memory:learning_progress")],
                [InlineKeyboardButton("⬅️ Main Menu", callback_data="menu:main")],
            ]
        )

    def _reports_keyboard(self):
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Daily Report", callback_data="reports:daily")],
                [InlineKeyboardButton("Weekly Report", callback_data="reports:weekly")],
                [InlineKeyboardButton("Monthly Report", callback_data="reports:monthly")],
                [InlineKeyboardButton("Export Trade Log", callback_data="reports:export_trade_log")],
                [InlineKeyboardButton("⬅️ Main Menu", callback_data="menu:main")],
            ]
        )

    def _confirmation_keyboard(self, action: str):
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Yes", callback_data=f"confirm:{action}:yes"),
                    InlineKeyboardButton("No", callback_data=f"confirm:{action}:no"),
                ],
            ]
        )

    def _systeem_keyboard(self):
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Ping (Is bot actief?)", callback_data="systeem:ping")],
                [InlineKeyboardButton("Laatste Logs (40 regels)", callback_data="systeem:logs")],
                [InlineKeyboardButton("Portfolio Heat", callback_data="systeem:heat")],
                [InlineKeyboardButton("Herstart Bot", callback_data="systeem:restart")],
                [InlineKeyboardButton("⬅️ Main Menu", callback_data="menu:main")],
            ]
        )

    def _menu_keyboard(self, section: str):
        mapping = {
            "dashboard": self._dashboard_keyboard,
            "control": self._control_keyboard,
            "risk": self._risk_keyboard,
            "signals": self._signals_keyboard,
            "memory": self._memory_keyboard,
            "backtest": self._backtest_keyboard,
            "reports": self._reports_keyboard,
            "systeem": self._systeem_keyboard,
        }
        return mapping.get(section, self._main_menu_keyboard)()

    def _format_status_detail(self, field: str, data: dict[str, Any]) -> str:
        mapping = {
            "account_status": f"Account Status\n{data.get('account_status', 'unknown').upper()}",
            "equity": f"Equity\n€{float(data.get('equity', 0.0)):,.2f}",
            "balance": f"Balance\n€{float(data.get('balance', 0.0)):,.2f}",
            "open_pnl": f"Open PnL\n€{float(data.get('open_pnl', 0.0)):,.2f}",
            "daily_pnl": f"Daily PnL\n€{float(data.get('daily_pnl', 0.0)):,.2f}",
            "weekly_pnl": f"Weekly PnL\n€{float(data.get('weekly_pnl', 0.0)):,.2f}",
            "monthly_pnl": f"Monthly PnL\n€{float(data.get('monthly_pnl', 0.0)):,.2f}",
            "drawdown": (
                f"Drawdown\n€{float(data.get('drawdown', 0.0)):,.2f}\n{float(data.get('drawdown_pct', 0.0)):.2f}%"
            ),
            "ftmo_status": (
                "FTMO Status\n"
                f"{data.get('ftmo_status', {}).get('status', 'unknown')}\n"
                f"Can trade: {'YES' if data.get('ftmo_status', {}).get('can_trade') else 'NO'}"
            ),
        }
        return mapping.get(field, data.get("summary", "Geen data beschikbaar"))

    def _button_label(self, action: str) -> str:
        labels = {
            "start_bot": "Start Bot",
            "stop_bot": "Stop Bot",
            "pause_trading": "Pause Trading",
            "resume_trading": "Resume Trading",
            "emergency_stop": "Emergency Stop",
            "close_all_positions": "Close All Positions",
        }
        return labels.get(action, action)
