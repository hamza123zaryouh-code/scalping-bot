"""Run a manual end-to-end webapp CRUD smoke test against Supabase-backed routes."""
from __future__ import annotations

import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv
from jose import jwt

ROOT = Path(__file__).resolve().parents[1]
ACCESS_COOKIE = "bot-access-token"


def _load_environment() -> None:
    load_dotenv(ROOT / ".env")


def _read_env(name: str) -> str:
    return os.getenv(name, "").strip()


def _resolve_shared_secret() -> str:
    secret = (
        _read_env("BACKEND_JWT_SECRET")
        or _read_env("JWT_SHARED_SECRET")
        or _read_env("SECRET_KEY")
        or _read_env("JWT_SECRET")
    )
    if not secret:
        raise RuntimeError(
            "Missing shared JWT secret. Set BACKEND_JWT_SECRET, JWT_SHARED_SECRET, or SECRET_KEY."
        )
    return secret


def _build_access_token(secret: str, username: str) -> str:
    payload = {
        "sub": username,
        "role": "admin",
        "name": "Supabase CRUD Check",
        "email": f"{username}@local.invalid",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def _assert_ok(response: httpx.Response, expected_status: int | tuple[int, ...], context: str) -> dict:
    accepted = expected_status if isinstance(expected_status, tuple) else (expected_status,)
    if response.status_code not in accepted:
        raise RuntimeError(f"{context} failed with {response.status_code}: {response.text}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"{context} returned non-JSON output: {response.text}") from exc

    warning = payload.get("warning")
    if warning:
        raise RuntimeError(f"{context} returned a migration/config warning instead of a clean success: {warning}")

    return payload


def main() -> int:
    _load_environment()

    webapp_base_url = _read_env("WEBAPP_BASE_URL") or "http://127.0.0.1:3000"
    username = _read_env("AUTH_ADMIN_USERNAME") or "admin"
    token = _build_access_token(_resolve_shared_secret(), username)
    today = date.today().isoformat()
    trade_id: str | None = None

    profile_update = {
        "displayName": "Supabase CRUD Check",
        "preferredCurrency": "USD",
        "dailyLossLimit": 500,
        "maxLossLimit": 1000,
    }

    trade_payload = {
        "symbol": "XAUUSD",
        "tradeType": "Buy",
        "date": today,
        "entryPrice": 2300,
        "currentPrice": 2310,
        "entryZoneFrom": 2298,
        "entryZoneTo": 2302,
        "lotSize": 0.1,
        "stopLoss": 2290,
        "tp1": 2310,
        "tp2": 2320,
        "tp3": 2330,
        "tp4": 2340,
        "status": "TP hit",
        "reasonForEntry": f"Manual CRUD smoke {uuid.uuid4()}",
    }

    with httpx.Client(base_url=webapp_base_url.rstrip("/"), follow_redirects=True, timeout=20.0) as client:
        client.cookies.set(ACCESS_COOKIE, token)

        session_payload = _assert_ok(client.get("/api/auth/session"), 200, "Session check")
        if not session_payload.get("authenticated"):
            raise RuntimeError("Webapp did not accept the shared JWT token.")

        _assert_ok(client.get("/api/profile"), 200, "Profile read")
        updated_profile = _assert_ok(client.put("/api/profile", json=profile_update), 200, "Profile update")
        if updated_profile["profile"]["preferredCurrency"] != "USD":
            raise RuntimeError("Profile update did not persist the preferred currency.")

        created_trade = _assert_ok(client.post("/api/trades", json=trade_payload), 201, "Trade create")
        trade_id = created_trade["trade"]["id"]

        listed_trades = _assert_ok(client.get("/api/trades"), 200, "Trade list")
        if not any(trade.get("id") == trade_id for trade in listed_trades.get("trades", [])):
            raise RuntimeError("Created trade was not returned by the trade list route.")

        updated_trade = _assert_ok(
            client.put(
                f"/api/trades/{trade_id}",
                json={
                    **trade_payload,
                    "currentPrice": 2335,
                    "status": "manually closed",
                    "satisfactionReason": "Manual CRUD update",
                },
            ),
            200,
            "Trade update",
        )
        if updated_trade["trade"]["status"] != "manually closed":
            raise RuntimeError("Trade update did not persist the updated status.")

        _assert_ok(client.delete(f"/api/trades/{trade_id}"), 200, "Trade delete")
        trade_id = None

        final_list = _assert_ok(client.get("/api/trades"), 200, "Trade list after delete")
        if any(trade.get("id") == created_trade["trade"]["id"] for trade in final_list.get("trades", [])):
            raise RuntimeError("Deleted trade is still present after the delete route.")

    print(f"Manual trade/profile CRUD check passed against {webapp_base_url}.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - operational script
        print(f"Supabase CRUD smoke test failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
