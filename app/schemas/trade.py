from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.signal import TradeSignal
from app.schemas.signal import MarketType, PositionSide, SignalIntent


class PaperTradeRequest(BaseModel):
    signal: TradeSignal
    quantity: float | None = Field(default=None, gt=0)


class PaperTradeResult(BaseModel):
    id: int | None = None
    symbol: str
    action: Literal["BUY", "SELL"]
    market_type: MarketType = "spot"
    intent: SignalIntent = "open"
    position_side: PositionSide = "long"
    quantity: float = Field(..., gt=0)
    entry_price: float
    stop_loss: float
    take_profit: float | None = None
    risk_amount: float = Field(..., ge=0)
    status: Literal["OPEN"] = "OPEN"
    execution_mode: str = "paper"
    exchange_order_id: str | None = None
    exchange_status: str | None = None
    protective_order_list_id: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ClosePositionRequest(BaseModel):
    exit_price: float = Field(..., gt=0)
    exit_reason: str = Field(default="manual", min_length=1)


class PaperPosition(BaseModel):
    id: int
    symbol: str
    action: Literal["BUY", "SELL"]
    market_type: MarketType = "spot"
    intent: SignalIntent = "open"
    position_side: PositionSide = "long"
    status: Literal["OPEN", "CLOSED"]
    quantity: float
    entry_price: float
    stop_loss: float
    take_profit: float | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    realized_pnl: float | None = None
    current_price: float | None = None
    unrealized_pnl: float | None = None
    risk_amount: float
    execution_mode: str = "paper"
    exchange_order_id: str | None = None
    exchange_status: str | None = None
    close_exchange_order_id: str | None = None
    protective_order_list_id: str | None = None
    protective_order_status: str | None = None
    opened_at: datetime
    closed_at: datetime | None = None

    model_config = {"from_attributes": True}
