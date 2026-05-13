from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from typing import Any

try:
    from telegram import Update
    from telegram.ext import Application, CommandHandler, ContextTypes

    TELEGRAM_AVAILABLE = True
except ImportError:  # pragma: no cover
    Update = Any  # type: ignore[assignment]
    Application = None  # type: ignore[assignment]
    CommandHandler = None  # type: ignore[assignment]
    ContextTypes = Any  # type: ignore[assignment]
    TELEGRAM_AVAILABLE = False


logger = logging.getLogger(__name__)


class TelegramControlLayer:
    def __init__(
        self,
        token: str,
        chat_id: str,
        status_callback: Callable[[], str],
        stop_callback: Callable[[], str],
        train_callback: Callable[[], str],
    ) -> None:
        self.token = token
        self.chat_id = chat_id
        self.status_callback = status_callback
        self.stop_callback = stop_callback
        self.train_callback = train_callback
        self.enabled = bool(token and chat_id and TELEGRAM_AVAILABLE)
        self._thread: threading.Thread | None = None
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
        if Application is None or CommandHandler is None:
            return
        application = Application.builder().token(self.token).build()
        application.add_handler(CommandHandler("status", self._on_status))
        application.add_handler(CommandHandler("stop", self._on_stop))
        application.add_handler(CommandHandler("train", self._on_train))

        await application.initialize()
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)
        while True:  # pragma: no cover - long-running service
            await asyncio.sleep(3600)

    async def _reply(self, update: Update, text: str) -> None:
        if update.effective_message:
            await update.effective_message.reply_text(text[:4000])

    async def _on_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:  # noqa: ARG002
        await self._reply(update, self.status_callback())

    async def _on_stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:  # noqa: ARG002
        await self._reply(update, self.stop_callback())

    async def _on_train(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:  # noqa: ARG002
        await self._reply(update, self.train_callback())
