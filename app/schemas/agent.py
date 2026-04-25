from pydantic import BaseModel

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
