from pydantic import BaseModel, Field

from app.schemas.risk import RiskDecision
from app.schemas.signal import SignalRequest, TradeSignal
from app.schemas.trade import PaperPosition, PaperTradeResult


class AgentRunResult(BaseModel):
    signal: TradeSignal
    risk_decision: RiskDecision
    execution_result: PaperTradeResult | None = None


class AgentTickRequest(SignalRequest):
    current_price: float | None = None
    open_new_position: bool = True


class AgentTickResult(BaseModel):
    closed_positions: list[PaperPosition]
    run_result: AgentRunResult | None = None
    reason: str


class AutonomousStartRequest(BaseModel):
    symbols: list[str] = Field(default_factory=lambda: ["BTCUSDT"], min_length=1)
    timeframe: str = "1H"
    market_context: str = Field(
        default="Precio en tendencia alcista con ruptura y volumen creciente.",
        min_length=1,
    )
    interval_seconds: float = Field(default=60, ge=5)
    open_new_position: bool = True


class AutonomousRunnerStatus(BaseModel):
    running: bool
    symbols: list[str]
    timeframe: str
    interval_seconds: float
    open_new_position: bool
    last_tick_at: str | None = None
    last_results: dict = Field(default_factory=dict)
    last_error: str | None = None
