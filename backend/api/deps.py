"""FastAPI dependency injections — auth, settings, services."""
from __future__ import annotations

import logging

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.core.config import Settings, get_settings
from backend.core.security import decode_access_token

logger = logging.getLogger(__name__)
_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Validate JWT and return token payload. Raises 401 on failure."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return decode_access_token(credentials.credentials)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def get_api_key(
    x_api_key: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> str:
    """Simple API-key guard for machine-to-machine calls (optional second factor)."""
    expected = getattr(settings, "api_key", None)
    if expected and x_api_key != expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API key")
    return x_api_key or ""


def require_telegram_api_key(
    x_api_key: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> str:
    expected = settings.telegram_api_key
    if not expected or x_api_key != expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid Telegram control API key")
    return x_api_key or ""


def assert_telegram_owner(telegram_user_id: str, settings: Settings) -> None:
    """Raise 403 if telegram_user_id does not match the configured owner.

    Fails closed: if TELEGRAM_OWNER_USER_ID is not configured, every request is rejected.
    """
    owner = settings.telegram_owner_user_id.strip()
    if not owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Telegram owner not configured")
    if telegram_user_id != owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized Telegram user")
