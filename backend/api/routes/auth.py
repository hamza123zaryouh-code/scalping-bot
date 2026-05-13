"""Authentication endpoints."""
from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from backend.core.config import Settings, get_settings
from backend.core.security import create_access_token, verify_password

logger = logging.getLogger(__name__)
router = APIRouter()


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


def _authenticate_user(settings: Settings, username: str, password: str) -> dict[str, str] | None:
    if username != settings.auth_admin_username:
        return None
    if not verify_password(password, settings.auth_admin_password_hash or ""):
        return None
    return {"username": settings.auth_admin_username, "role": "admin"}


@router.post("/token", response_model=Token, summary="Obtain JWT access token")
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
    settings: Settings = Depends(get_settings),
):
    user = _authenticate_user(settings, form.username, form.password)
    if user is None:
        logger.warning("Failed login attempt for user '%s'", form.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(
        {"sub": user["username"], "role": user["role"]},
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
    )
    logger.info("Token issued for '%s'", form.username)
    return Token(access_token=token, role=user["role"])
