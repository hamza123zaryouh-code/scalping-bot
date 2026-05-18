#!/usr/bin/env python3
"""
Quick Telegram button test — no MT5 / trading system required.
Run this to verify the bot token + chat_id work and that buttons appear.

Usage:
    python scripts/test_telegram_buttons.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

load_dotenv(_ROOT / ".env")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
OWNER_ID = os.getenv("TELEGRAM_OWNER_USER_ID", "")


async def main() -> None:
    if not BOT_TOKEN or not CHAT_ID:
        print("ERROR: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set in .env")
        sys.exit(1)

    print(f"Bot token : {BOT_TOKEN[:20]}...")
    print(f"Chat ID   : {CHAT_ID}")
    print(f"Owner ID  : {OWNER_ID}")
    print()

    try:
        from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
    except ImportError:
        print("ERROR: python-telegram-bot is not installed. Run: pip install python-telegram-bot")
        sys.exit(1)

    bot = Bot(token=BOT_TOKEN)

    # Test 1: get bot info
    print("Testing bot connection...")
    me = await bot.get_me()
    print(f"Connected as: @{me.username} ({me.first_name})")
    print()

    # Test 2: send a message with buttons
    print("Sending test message with buttons to chat...")
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("✅ Bot werkt!", callback_data="test:ok")],
            [
                InlineKeyboardButton("📊 Dashboard", callback_data="menu:dashboard"),
                InlineKeyboardButton("⚙️ Control", callback_data="menu:control"),
            ],
            [
                InlineKeyboardButton("🛡 Risk", callback_data="menu:risk"),
                InlineKeyboardButton("📡 Signals", callback_data="menu:signals"),
            ],
        ]
    )

    msg = await bot.send_message(
        chat_id=CHAT_ID,
        text=(
            "🤖 *XAUUSD Bot — Telegram Test*\n\n"
            "Knoppen zijn actief. Dit bericht bevestigt dat de bot correct is geconfigureerd.\n\n"
            "_Stuur /start zodra de bot draait voor het volledige menu._"
        ),
        reply_markup=keyboard,
        parse_mode="Markdown",
    )
    print(f"Message sent! Message ID: {msg.message_id}")
    print()

    # Test 3: simple polling (5 seconds) to catch /start
    print("Listening for 5 seconds (send /start to test the handler)...")
    print("Press Ctrl+C to stop early.")
    print()

    from telegram import Update
    from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

    app = Application.builder().token(BOT_TOKEN).build()

    async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_message:
            await update.effective_message.reply_text(
                "✅ /start werkt! Bot is operationeel.\n\n"
                "Stuur /start wanneer de echte bot draait voor het volledige menu.",
                reply_markup=keyboard,
            )

    async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if query:
            await query.answer("Knop ontvangen!")
            await query.edit_message_text(f"Knop: `{query.data}` — werkt correct!", parse_mode="Markdown")

    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(CallbackQueryHandler(on_callback))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    try:
        await asyncio.sleep(30)
    except asyncio.CancelledError:
        pass
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

    print("Test complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nTest gestopt.")
