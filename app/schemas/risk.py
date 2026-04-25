from pydantic import BaseModel, Field

from app.schemas.signal import TradeSignal
from app.schemas.system import AccountState


class RiskDecision(BaseModel):
    approved: bool
    reason: str
    risk_amount: float = 0
    max_allowed_risk: float = 0
    quantity: float | None = None


class RiskValidationRequest(BaseModel):
    signal: TradeSignal
    account_state: AccountState

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "signal": {
                        "symbol": "BTCUSDT",
                        "action": "BUY",
                        "confidence": 0.72,
                        "entry_price": 64200,
                        "stop_loss": 62800,
                        "take_profit": 67000,
                        "risk_amount": 10,
                        "reason": "Ruptura con volumen creciente.",
                    },
                    "account_state": {
                        "equity": 1000,
                        "daily_loss": 0,
                        "weekly_loss": 0,
                        "trades_today": 0,
                        "trading_enabled": True,
                    },
                }
            ]
        }
    }


class RiskLimits(BaseModel):
    max_daily_loss: float = Field(..., ge=0)
    max_weekly_loss: float = Field(..., ge=0)
    max_trades_per_day: int = Field(..., ge=0)
    max_risk_per_trade_percent: float = Field(..., gt=0)
    min_confidence: float = Field(..., ge=0, le=1)
