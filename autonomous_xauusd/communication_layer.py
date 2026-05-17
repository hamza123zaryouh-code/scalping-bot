from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from typing import Any

import httpx

from autonomous_xauusd.memory_layer import MemoryLayer
from autonomous_xauusd.settings import load_settings
from backend.main import create_app

try:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
    from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

    TELEGRAM_AVAILABLE = True
except ImportError:  # pragma: no cover
    Update = Any  # type: ignore[assignment]
    Application = None  # type: ignore[assignment]
    CallbackQueryHandler = None  # type: ignore[assignment]
    CommandHandler = None  # type: ignore[assignment]
    ContextTypes = Any  # type: ignore[assignment]
    InlineKeyboardButton = InlineKeyboardMarkup = Any  # type: ignore[assignment]
    TELEGRAM_AVAILABLE = False


logger = logging.getLogger(__name__)

_API_APP = create_app()


class TelegramBackendClient:
    def __init__(self, api_key: str, base_url: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def get(self, path: str) -> dict[str, Any]:
        transport = httpx.ASGITransport(app=_API_APP)
        async with httpx.AsyncClient(
            transport=transport,
            base_url=self.base_url,
            headers={"X-API-Key": self.api_key},
            timeout=120.0,
        ) as client:
            response = await client.get(path)
            response.raise_for_status()
            return response.json()

    async def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        transport = httpx.ASGITransport(app=_API_APP)
        async with httpx.AsyncClient(
            transport=transport,
            base_url=self.base_url,
            headers={"X-API-Key": self.api_key},
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
    ) -> None:
        self.token = token
        self.chat_id = chat_id
        self.owner_user_id = owner_user_id.strip()
        self.status_callback = status_callback
        self.stop_callback = stop_callback
        self.train_callback = train_callback
        self.enabled = bool(token and chat_id and TELEGRAM_AVAILABLE)
        self._thread: threading.Thread | None = None
        self._backend = TelegramBackendClient(api_key=backend_api_key, base_url=backend_base_url)
        self._memory = MemoryLayer(load_settings().database_url)
        self._memory.initialize()

        if token and chat_id and not TELEGRAM_AVAILABLE:
            logger.warning("python-telegram-bot is not installed; Telegram control layer is disabled.")

    def start_in_background(self) -> None:
        if not self.enabled or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run_polling, name="telegram-control", daemon=True)
        self._thread.start()

    def notify(self, message: str) -> bool:
        if not self.enabled:
            return False

        try:
            asyncio.run(self._send_message(message))
            return True
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(self._send_message(message))
                return True
            finally:
                loop.close()
        except Exception as exc:  # pragma: no cover - network dependent
            logger.warning("Telegram notification failed: %s", exc)
            return False

    async def _send_message(self, message: str) -> None:
        if Application is None:
            return
        application = Application.builder().token(self.token).build()
        await application.bot.send_message(chat_id=self.chat_id, text=message[:4000])

    def _run_polling(self) -> None:
        asyncio.run(self._run_application())

    async def _run_application(self) -> None:
        if Application is None or CommandHandler is None or CallbackQueryHandler is None:
            return

        application = Application.builder().token(self.token).build()
        application.add_handler(CommandHandler("start", self._on_start))
        application.add_handler(CommandHandler("menu", self._on_start))
        application.add_handler(CommandHandler("status", self._on_status))
        application.add_handler(CallbackQueryHandler(self._on_callback))

        await application.initialize()
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)
        while True:  # pragma: no cover - long-running service
            await asyncio.sleep(3600)

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

    async def _on_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:  # noqa: ARG002
        if not self._is_authorized(update):
            await self._deny_access(update, "command_status")
            return

        self._log_user_action(update, "command_status", "success", {})
        response = await self._backend.get("/api/v1/telegram/status")
        summary = response["data"]["summary"]
        if update.effective_message:
            await update.effective_message.reply_text(summary[:4000], reply_markup=self._dashboard_keyboard())

    async def _on_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:  # noqa: ARG002
        query = update.callback_query
        if query is None:
            return

        if not self._is_authorized(update):
            await self._deny_access(update, query.data or "unknown", query=query)
            return

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
        except httpx.HTTPStatusError as exc:
            logger.warning("Telegram backend HTTP error: %s", exc)
            self._log_user_action(update, data, "error", {"detail": str(exc)})
            await query.answer("Backend fout", show_alert=True)
            await query.edit_message_text(
                f"Actie mislukt:\n{exc.response.text[:3500]}",
                reply_markup=self._main_menu_keyboard(),
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Telegram callback failed")
            self._log_user_action(update, data, "error", {"detail": str(exc)})
            await query.answer("Onverwachte fout", show_alert=True)
            await query.edit_message_text(
                f"Onverwachte fout:\n{str(exc)[:3500]}",
                reply_markup=self._main_menu_keyboard(),
            )

    async def _handle_confirmation(self, update: Update, query, data: str) -> None:
        _, action, decision = data.split(":", 2)
        if decision == "no":
            self._log_user_action(update, f"{action}_cancelled", "cancelled", {})
            await query.answer("Geannuleerd")
            await query.edit_message_text(
                "Actie geannuleerd.",
                reply_markup=self._menu_keyboard("control"),
            )
            return

        payload = self._identity_payload(update, confirmed=True)
        response = await self._backend.post(f"/api/v1/telegram/control/{action}", payload)
        text = response["data"]["summary"]
        self._log_user_action(update, action, "confirmed", {"response": text})
        await query.answer("Bevestigd")
        await query.edit_message_text(text[:4000], reply_markup=self._menu_keyboard("control"))

    async def _handle_action(self, update: Update, query, data: str) -> None:
        if data == "status:overview":
            response = await self._backend.get("/api/v1/telegram/status")
            text = response["data"]["summary"]
            keyboard = self._dashboard_keyboard()
        elif data.startswith("status:"):
            response = await self._backend.get("/api/v1/telegram/status")
            text = self._format_status_detail(data.split(":", 1)[1], response["data"])
            keyboard = self._dashboard_keyboard()
        elif data.startswith("control:"):
            action = data.split(":", 1)[1]
            payload = self._identity_payload(update)
            response = await self._backend.post(f"/api/v1/telegram/control/{action}", payload)
            result = response["data"]
            if result.get("requires_confirmation"):
                self._log_user_action(update, action, "confirmation_required", {})
                await query.answer("Bevestiging nodig")
                await query.edit_message_text(
                    f"Weet je zeker dat je '{self._button_label(action)}' wilt uitvoeren?",
                    reply_markup=self._confirmation_keyboard(action),
                )
                return
            text = result["summary"]
            keyboard = self._menu_keyboard("control")
        elif data.startswith("risk:"):
            section = data.split(":", 1)[1]
            response = await self._backend.get(f"/api/v1/telegram/risk/{section}")
            text = response["data"]["summary"]
            keyboard = self._menu_keyboard("risk")
        elif data.startswith("signals_toggle:"):
            enabled = data.endswith(":on")
            response = await self._backend.post(
                "/api/v1/telegram/signals/toggle",
                {**self._identity_payload(update), "enabled": enabled},
            )
            text = response["data"]["summary"]
            keyboard = self._menu_keyboard("signals")
        elif data.startswith("signals:"):
            section = data.split(":", 1)[1]
            response = await self._backend.get(f"/api/v1/telegram/signals/{section}")
            text = response["data"]["summary"]
            keyboard = self._menu_keyboard("signals")
        elif data == "backtest:quick_run":
            response = await self._backend.post("/api/v1/telegram/backtest/quick-run", self._identity_payload(update))
            text = response["data"]["summary"]
            keyboard = self._menu_keyboard("backtest")
        elif data == "backtest:latest":
            response = await self._backend.get("/api/v1/telegram/backtest/latest")
            text = response["data"]["summary"]
            keyboard = self._menu_keyboard("backtest")
        elif data == "backtest:compare":
            response = await self._backend.get("/api/v1/telegram/backtest/compare")
            text = response["data"]["summary"]
            keyboard = self._menu_keyboard("backtest")
        elif data == "backtest:equity_curve":
            response = await self._backend.get("/api/v1/telegram/backtest/equity-curve-summary")
            text = response["data"]["summary"]
            keyboard = self._menu_keyboard("backtest")
        elif data == "memory:train":
            response = await self._backend.post("/api/v1/telegram/memory/train", self._identity_payload(update))
            text = response["data"]["summary"]
            keyboard = self._menu_keyboard("memory")
        elif data.startswith("memory:"):
            section = data.split(":", 1)[1]
            response = await self._backend.get(f"/api/v1/telegram/memory/{section}")
            text = response["data"]["summary"]
            keyboard = self._menu_keyboard("memory")
        elif data.startswith("reports:"):
            section = data.split(":", 1)[1]
            if section == "export_trade_log":
                response = await self._backend.post(
                    "/api/v1/telegram/reports/export-trade-log",
                    self._identity_payload(update),
                )
            else:
                response = await self._backend.get(f"/api/v1/telegram/reports/{section}")
            text = response["data"]["summary"]
            keyboard = self._menu_keyboard("reports")
        else:
            raise ValueError(f"Unsupported callback: {data}")

        self._log_user_action(update, data, "success", {"summary": text[:500]})
        await query.answer("Uitgevoerd")
        await query.edit_message_text(text[:4000], reply_markup=keyboard)

    async def _deny_access(self, update: Update, action: str, query=None) -> None:
        self._log_user_action(update, action, "denied", {"owner_user_id": self.owner_user_id})
        if query is not None:
            await query.answer("Geen toegang", show_alert=True)
            return
        if update.effective_message:
            await update.effective_message.reply_text("Geen toegang. Alleen de geconfigureerde owner kan deze bot bedienen.")

    def _is_authorized(self, update: Update) -> bool:
        if not self.owner_user_id:
            logger.warning("TELEGRAM_OWNER_USER_ID is not configured; Telegram controls are disabled.")
            return False
        user = update.effective_user
        if user is None:
            return False
        return str(user.id) == self.owner_user_id

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
            ]
        )

    def _dashboard_keyboard(self):
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Account Status", callback_data="status:account_status")],
                [InlineKeyboardButton("Equity", callback_data="status:equity"), InlineKeyboardButton("Balance", callback_data="status:balance")],
                [InlineKeyboardButton("Open PnL", callback_data="status:open_pnl"), InlineKeyboardButton("Daily PnL", callback_data="status:daily_pnl")],
                [InlineKeyboardButton("Weekly PnL", callback_data="status:weekly_pnl"), InlineKeyboardButton("Monthly PnL", callback_data="status:monthly_pnl")],
                [InlineKeyboardButton("Drawdown", callback_data="status:drawdown"), InlineKeyboardButton("FTMO Status", callback_data="status:ftmo_status")],
                [InlineKeyboardButton("Refresh Overview", callback_data="status:overview")],
                [InlineKeyboardButton("⬅️ Main Menu", callback_data="menu:main")],
            ]
        )

    def _control_keyboard(self):
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Start Bot", callback_data="control:start_bot"), InlineKeyboardButton("Stop Bot", callback_data="control:stop_bot")],
                [InlineKeyboardButton("Pause Trading", callback_data="control:pause_trading"), InlineKeyboardButton("Resume Trading", callback_data="control:resume_trading")],
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
                [InlineKeyboardButton("Yes", callback_data=f"confirm:{action}:yes"), InlineKeyboardButton("No", callback_data=f"confirm:{action}:no")],
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
        }
        return mapping[section]()

    def _format_status_detail(self, field: str, data: dict[str, Any]) -> str:
        mapping = {
            "account_status": f"Account Status\n{data.get('account_status', 'unknown').upper()}",
            "equity": f"Equity\n${float(data.get('equity', 0.0)):,.2f}",
            "balance": f"Balance\n${float(data.get('balance', 0.0)):,.2f}",
            "open_pnl": f"Open PnL\n${float(data.get('open_pnl', 0.0)):,.2f}",
            "daily_pnl": f"Daily PnL\n${float(data.get('daily_pnl', 0.0)):,.2f}",
            "weekly_pnl": f"Weekly PnL\n${float(data.get('weekly_pnl', 0.0)):,.2f}",
            "monthly_pnl": f"Monthly PnL\n${float(data.get('monthly_pnl', 0.0)):,.2f}",
            "drawdown": (
                f"Drawdown\n${float(data.get('drawdown', 0.0)):,.2f}\n"
                f"{float(data.get('drawdown_pct', 0.0)):.2f}%"
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
