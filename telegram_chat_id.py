from __future__ import annotations

import argparse
from pathlib import Path

import requests
from dotenv import load_dotenv
import os


def load_token(base_dir: Path) -> str:
    load_dotenv(base_dir / ".env")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN ontbreekt in .env")
    return token


def get_recent_chats(token: str) -> list[dict]:
    response = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=30)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram API error: {payload}")

    chats: dict[str, dict] = {}
    for item in payload.get("result", []):
        message = item.get("message") or item.get("my_chat_member") or item.get("channel_post") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if chat_id is None:
            continue
        chats[str(chat_id)] = {
            "chat_id": str(chat_id),
            "type": chat.get("type", ""),
            "title": chat.get("title", ""),
            "username": chat.get("username", ""),
            "first_name": chat.get("first_name", ""),
            "last_name": chat.get("last_name", ""),
        }
    return list(chats.values())


def main() -> None:
    parser = argparse.ArgumentParser(description="Toon recente Telegram chat IDs voor deze bot.")
    parser.parse_args()

    base_dir = Path(__file__).resolve().parent
    token = load_token(base_dir)
    chats = get_recent_chats(token)

    if not chats:
        print("Geen chat updates gevonden. Stuur eerst een bericht of /start naar je bot en run daarna dit script opnieuw.")
        return

    print("Gevonden Telegram chats:")
    for chat in chats:
        name = " ".join(part for part in [chat["title"], chat["first_name"], chat["last_name"]] if part).strip()
        if not name:
            name = chat["username"] or "Onbekende chat"
        print(
            f"- CHAT_ID={chat['chat_id']} | type={chat['type']} | naam={name} | username={chat['username'] or '-'}"
        )


if __name__ == "__main__":
    main()
