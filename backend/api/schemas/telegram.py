"""Schemas for Telegram control endpoints."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TelegramActionRequest(BaseModel):
    telegram_user_id: str = Field(min_length=1)
    telegram_username: str | None = None
    confirmed: bool = False


class TelegramToggleRequest(BaseModel):
    telegram_user_id: str = Field(min_length=1)
    telegram_username: str | None = None
    enabled: bool


class TelegramActionResponse(BaseModel):
    action: str
    status: str
    summary: str
    requires_confirmation: bool = False
    command_id: int | None = None
    data: dict[str, Any] = Field(default_factory=dict)
