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
    timeframe: str = "15M"
    market_context: str = Field(
        default="Analiza el mercado con los datos calculados por el backend. Opera solo si hay ventaja clara.",
        min_length=1,
    )
    interval_seconds: float = Field(default=60, ge=5)
    open_new_position: bool = True
    align_to_candle_close: bool = True


class AutonomousRunnerStatus(BaseModel):
    running: bool
    symbols: list[str]
    timeframe: str
    interval_seconds: float
    open_new_position: bool
    align_to_candle_close: bool = False
    last_tick_at: str | None = None
    last_results: dict = Field(default_factory=dict)
    last_error: str | None = None
    consecutive_errors: int = 0
    circuit_breaker_tripped: bool = False
    circuit_breaker_reason: str | None = None
