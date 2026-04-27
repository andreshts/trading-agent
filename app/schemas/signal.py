from typing import Literal

from pydantic import BaseModel, Field, field_validator


class SignalRequest(BaseModel):
    symbol: str = Field(..., examples=["BTCUSDT"], min_length=1)
    timeframe: str = Field(..., examples=["1h"], min_length=1)
    market_context: str = Field(..., min_length=1)
    idempotency_key: str | None = Field(
        default=None,
        description=(
            "Optional caller-supplied identifier to deduplicate retries. "
            "When provided, an order intent with this id will be reused "
            "instead of opening a duplicate position."
        ),
        max_length=80,
    )

    @field_validator("symbol", "timeframe")
    @classmethod
    def normalize_upper(cls, value: str) -> str:
        return value.strip().upper()


class TradeSignal(BaseModel):
    symbol: str = Field(..., min_length=1)
    action: Literal["BUY", "SELL", "HOLD"]
    confidence: float = Field(..., ge=0, le=1)
    entry_price: float | None = Field(default=None, gt=0)
    stop_loss: float | None = Field(default=None, gt=0)
    take_profit: float | None = Field(default=None, gt=0)
    risk_amount: float = Field(default=0, ge=0)
    reason: str = Field(..., min_length=1)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.strip().upper()
