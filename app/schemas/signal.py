from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


MarketType = Literal["spot", "futures", "margin"]
SignalIntent = Literal["open", "close", "reduce"]
PositionSide = Literal["long", "short"]


class SignalRequest(BaseModel):
    symbol: str = Field(..., examples=["BTCUSDT"], min_length=1)
    timeframe: str = Field(..., examples=["1h"], min_length=1)
    market_context: str = Field(..., min_length=1)
    market_type: MarketType = "spot"
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

    @field_validator("market_type")
    @classmethod
    def normalize_market_type(cls, value: str) -> str:
        return value.strip().lower()


class TradeSignal(BaseModel):
    symbol: str = Field(..., min_length=1)
    action: Literal["BUY", "SELL", "HOLD"]
    market_type: MarketType = "spot"
    intent: SignalIntent = "open"
    position_side: PositionSide | None = None
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

    @field_validator("market_type", "intent")
    @classmethod
    def normalize_lower(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("position_side")
    @classmethod
    def normalize_position_side(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip().lower()

    @model_validator(mode="after")
    def infer_position_side(self) -> "TradeSignal":
        if self.action == "HOLD":
            self.position_side = None
        elif self.position_side is None:
            self.position_side = "long" if self.action == "BUY" else "short"
        return self
