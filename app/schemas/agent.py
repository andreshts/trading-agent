from pydantic import BaseModel

from app.schemas.risk import RiskDecision
from app.schemas.signal import TradeSignal
from app.schemas.trade import PaperTradeResult


class AgentRunResult(BaseModel):
    signal: TradeSignal
    risk_decision: RiskDecision
    execution_result: PaperTradeResult | None = None

