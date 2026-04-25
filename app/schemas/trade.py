from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.signal import TradeSignal


class PaperTradeRequest(BaseModel):
    signal: TradeSignal


class PaperTradeResult(BaseModel):
    symbol: str
    action: Literal["BUY", "SELL"]
    entry_price: float
    stop_loss: float
    take_profit: float | None = None
    status: Literal["simulated"] = "simulated"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

