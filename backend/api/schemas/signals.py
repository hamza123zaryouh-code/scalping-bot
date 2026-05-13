"""Live signal schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class LiveSignalResponse(BaseModel):
    side: str                  # buy | sell | none
    entry_label: str
    trigger_time: datetime
    atr_value: float
    reference_price: float
    reason: str
    regime: str                # bull | bear | ranging
    confidence: float          # 0–1


class OpenPosition(BaseModel):
    ticket: int
    symbol: str
    side: str
    volume: float
    open_price: float
    current_price: float
    stop_loss: float
    take_profit: float
    unrealized_pnl: float
    open_time: datetime
    magic: int
    comment: str
