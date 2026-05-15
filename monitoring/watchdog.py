"""Watchdog service — monitors the platform and sends Telegram alerts on failure."""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path  # noqa: F401 — kept for potential future use

from monitoring.health_check import run_health_check

logger = logging.getLogger("watchdog")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

CHECK_INTERVAL_SECONDS = 60
FAILURE_ALERT_COOLDOWN = 300  # don't spam Telegram — one alert per 5 min per failure
BOT_DOWN_MAX_LOG_AGE_MINUTES = 3
_last_alerts: dict[str, float] = {}


def _send_telegram(message: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False
    try:
        import requests
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": f"[WATCHDOG] {message}"},
            timeout=10,
        )
        return r.ok
    except Exception as exc:
        logger.warning("Telegram send failed: %s", exc)
        return False


def _maybe_alert(check_name: str, message: str) -> None:
    now = time.time()
    last = _last_alerts.get(check_name, 0)
    if now - last >= FAILURE_ALERT_COOLDOWN:
        _last_alerts[check_name] = now
        _send_telegram(message)


def main() -> None:
    logger.info("Watchdog started — polling every %ds", CHECK_INTERVAL_SECONDS)
    while True:
        try:
            report = run_health_check(log_max_age_minutes=BOT_DOWN_MAX_LOG_AGE_MINUTES)
            if report.overall_ok:
                logger.info("Health OK — all %d checks passed", len(report.checks))
            else:
                failed = [c for c in report.checks if not c.ok]
                for c in failed:
                    logger.warning("HEALTH FAILURE: %s — %s", c.name, c.detail)
                    _maybe_alert(c.name, f"HEALTH FAILURE: {c.name} — {c.detail}")
        except Exception as exc:
            logger.exception("Watchdog cycle error: %s", exc)
        time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
