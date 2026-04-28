from pydantic import BaseModel, Field


class AccountState(BaseModel):
    equity: float = Field(..., gt=0)
    realized_pnl: float = 0
    daily_loss: float = Field(default=0, ge=0)
    weekly_loss: float = Field(default=0, ge=0)
    peak_equity: float | None = None
    drawdown: float = Field(default=0, ge=0)
    trades_today: int = Field(default=0, ge=0)
    open_positions: int = Field(default=0, ge=0)
    trading_enabled: bool = True


class KillSwitchRequest(BaseModel):
    reason: str = Field(default="Manual activation", min_length=1)


class KillSwitchStatus(BaseModel):
    enabled: bool
    active: bool
    reason: str | None = None


class SystemStatus(BaseModel):
    app_name: str
    app_env: str
    execution_mode: str
    trading_market_type: str = "spot"
    trading_enabled: bool
    paper_trading_enabled: bool
    real_trading_enabled: bool
    exchange_configured: bool
    allowed_symbols: list[str]
    max_notional_per_order: float
    kill_switch: KillSwitchStatus
    audit_events: int
    account: AccountState
