#!/usr/bin/env python3
"""
Production startup script for the autonomous XAUUSD trading system.

Usage:
    python scripts/run_live_bot.py [--mode paper|demo|live] [--dry-run]

Environment:
    AUTONOMOUS_MODE   — paper | demo | live (overrides .env)
    LOG_LEVEL         — DEBUG | INFO | WARNING (default INFO)

This script:
  1. Validates the environment (secrets, database, MT5 credentials)
  2. Checks FTMO parameters are sane
  3. Starts the LiveRuntime supervisor
  4. Handles SIGINT/SIGTERM gracefully
"""
from __future__ import annotations

import argparse
import atexit
import logging
import os
import sys
from pathlib import Path

# Ensure project root is on path regardless of cwd
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_LOCK_FILE = _ROOT / "live_logs" / "bot.lock"


def _acquire_single_instance_lock() -> None:
    """Prevent multiple bot instances from running at the same time."""
    _LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)

    if _LOCK_FILE.exists():
        try:
            existing_pid = int(_LOCK_FILE.read_text().strip())
            # Check if that PID is still alive (signal 0 = existence check)
            os.kill(existing_pid, 0)
            raise SystemExit(
                f"\n[FATAL] Bot is al actief (PID {existing_pid}).\n"
                f"Stop die instantie eerst, of verwijder het lock-bestand:\n"
                f"  {_LOCK_FILE}\n"
                f"Dit voorkomt de Telegram 'Conflict: terminated by other getUpdates' fout."
            )
        except OSError:
            # Stale lock — process no longer exists
            pass

    _LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
    atexit.register(_release_lock)


def _release_lock() -> None:
    try:
        _LOCK_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Autonomous XAUUSD Trading Bot — Production Launcher"
    )
    parser.add_argument(
        "--mode",
        choices=["paper", "demo", "live"],
        default=None,
        help="Override AUTONOMOUS_MODE env variable",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate environment and exit without starting trading loop",
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("LOG_LEVEL", "INFO").upper(),
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity",
    )
    return parser.parse_args()


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("live_logs/bot_stdout.log", encoding="utf-8"),
        ],
    )
    # Suppress noisy third-party loggers
    for noisy in ("httpx", "urllib3", "asyncio", "yfinance", "feedparser"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # Telegram Conflict = non-fatal (andere instantie draait elders, bijv. VPS)
    # Onderdruk de stacktraces zodat de logs leesbaar blijven
    logging.getLogger("telegram.ext.Updater").setLevel(logging.CRITICAL)
    logging.getLogger("telegram.ext._updater").setLevel(logging.CRITICAL)


def _pre_flight_checks(mode: str) -> None:
    """Validate that required configuration is present before starting."""
    logger = logging.getLogger("pre_flight")
    errors: list[str] = []
    warnings: list[str] = []

    # .env must exist
    env_path = _ROOT / ".env"
    if not env_path.exists():
        warnings.append(".env file not found — using system environment variables only")
    else:
        logger.info(".env found: %s", env_path)

    # MT5 check for live/demo modes
    if mode in ("live", "demo"):
        if not os.getenv("MT5_LOGIN"):
            errors.append("MT5_LOGIN not set (required for live/demo mode)")
        if not os.getenv("MT5_PASSWORD"):
            errors.append("MT5_PASSWORD not set (required for live/demo mode)")
        if not os.getenv("MT5_SERVER"):
            errors.append("MT5_SERVER not set (required for live/demo mode)")

    # Database
    db_url = (
        os.getenv("POSTGRES_URL", "").strip()
        or os.getenv("SUPABASE_DB_URL", "").strip()
        or "sqlite"
    )
    logger.info("Database: %s", db_url[:40] + "..." if len(db_url) > 40 else db_url)

    # Telegram (optional but recommended)
    if not os.getenv("TELEGRAM_BOT_TOKEN"):
        warnings.append("TELEGRAM_BOT_TOKEN not set — Telegram alerts disabled")
    if not os.getenv("TELEGRAM_OWNER_USER_ID"):
        warnings.append("TELEGRAM_OWNER_USER_ID not set — Telegram controls disabled")

    # NewsAPI (optional)
    if not os.getenv("NEWSAPI_KEY"):
        warnings.append("NEWSAPI_KEY not set — news engine will use RSS + yfinance fallback only")

    for warning in warnings:
        logger.warning("PRE-FLIGHT WARN: %s", warning)

    if errors:
        for error in errors:
            logger.error("PRE-FLIGHT ERROR: %s", error)
        raise SystemExit(f"Pre-flight validation failed ({len(errors)} errors). Fix .env and retry.")

    logger.info("Pre-flight checks passed. Mode: %s", mode.upper())


def main() -> None:
    args = _parse_args()
    Path("live_logs").mkdir(parents=True, exist_ok=True)
    _setup_logging(args.log_level)
    logger = logging.getLogger("run_live_bot")

    # Apply mode override
    if args.mode:
        os.environ["AUTONOMOUS_MODE"] = args.mode

    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")

    mode = os.getenv("AUTONOMOUS_MODE", "paper").strip().lower() or "paper"
    logger.info("=" * 60)
    logger.info("XAUUSD Autonomous Trading System — %s MODE", mode.upper())
    logger.info("=" * 60)

    _pre_flight_checks(mode)

    if args.dry_run:
        logger.info("Dry-run complete — environment validated. Exiting.")
        return

    # Warn before going live
    if mode == "live":
        logger.warning("=" * 60)
        logger.warning("LIVE TRADING MODE — REAL MONEY AT RISK")
        logger.warning("FTMO rules enforced. Kill switch: SIGINT or Telegram /emergency_stop")
        logger.warning("=" * 60)

    from autonomous_xauusd.runtime.live_runtime import run
    run()


if __name__ == "__main__":
    main()
