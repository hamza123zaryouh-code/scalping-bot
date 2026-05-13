from __future__ import annotations

from pathlib import Path

from config import load_live_bot_config


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    cfg = load_live_bot_config(base_dir)

    checks = [
        ("Telegram bot token", bool(cfg.telegram_bot_token)),
        ("Telegram chat id", bool(cfg.telegram_chat_id)),
        ("MT5 login", cfg.mt5_login > 0),
        ("MT5 password", bool(cfg.mt5_password)),
        ("MT5 server", bool(cfg.mt5_server)),
        ("Bot mode", cfg.bot_mode in {"paper", "demo", "live"}),
    ]

    print("LIVE READINESS CHECK")
    for label, ok in checks:
        print(f"- {label}: {'OK' if ok else 'MISSING'}")
    print(f"- Telegram daglimiet: {cfg.max_telegram_messages_per_day} berichten")
    print(f"- Heartbeat interval: {cfg.status_heartbeat_minutes} minuten")
    print(f"- Heartbeat naar Telegram: {'AAN' if cfg.send_heartbeat_to_telegram else 'UIT'}")

    if not cfg.telegram_chat_id:
        print("- Hint: stuur eerst /start naar je bot en run daarna `python telegram_chat_id.py`.")
    if cfg.bot_mode != "paper" and not cfg.mt5_ready:
        print("- Hint: vul eerst je MT5 demo credentials in .env in.")
    if cfg.bot_mode == "live" and not cfg.allow_live_account:
        print("- Hint: live mode blokkeert niet-demo accounts totdat ALLOW_LIVE_ACCOUNT=true staat.")


if __name__ == "__main__":
    main()
