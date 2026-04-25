from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.signal import TradeSignal


class PaperTradeRequest(BaseModel):
    signal: TradeSignal
    quantity: float | None = Field(default=None, gt=0)


class PaperTradeResult(BaseModel):
    id: int | None = None
    symbol: str
    action: Literal["BUY", "SELL"]
    quantity: float = Field(..., gt=0)
    entry_price: float
    stop_loss: float
    take_profit: float | None = None
    risk_amount: float = Field(..., ge=0)
    status: Literal["OPEN"] = "OPEN"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ClosePositionRequest(BaseModel):
    exit_price: float = Field(..., gt=0)
    exit_reason: str = Field(default="manual", min_length=1)


class PaperPosition(BaseModel):
    id: int
    symbol: str
    action: Literal["BUY", "SELL"]
    status: Literal["OPEN", "CLOSED"]
    quantity: float
    entry_price: float
    stop_loss: float
    take_profit: float | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    realized_pnl: float | None = None
    risk_amount: float
    opened_at: datetime
    closed_at: datetime | None = None

    model_config = {"from_attributes": True}
