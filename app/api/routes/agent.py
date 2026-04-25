from fastapi import APIRouter, Depends

from app.api.deps import (
    get_ai_signal_service,
    get_paper_executor,
    get_risk_manager,
    get_system_state,
)
from app.schemas.agent import AgentRunResult
from app.schemas.risk import RiskDecision
from app.schemas.signal import SignalRequest, TradeSignal
from app.services.ai_signal_service import AISignalService
from app.services.paper_trading import PaperTradingExecutor
from app.services.risk_manager import RiskManager
from app.services.system_state import SystemStateService


router = APIRouter()


@router.post("/signal", response_model=TradeSignal)
async def generate_signal(
    request: SignalRequest,
    signal_service: AISignalService = Depends(get_ai_signal_service),
) -> TradeSignal:
    return await signal_service.generate_signal(request)


@router.post("/run", response_model=AgentRunResult)
async def run_agent(
    request: SignalRequest,
    signal_service: AISignalService = Depends(get_ai_signal_service),
    risk_manager: RiskManager = Depends(get_risk_manager),
    executor: PaperTradingExecutor = Depends(get_paper_executor),
    system_state: SystemStateService = Depends(get_system_state),
) -> AgentRunResult:
    signal = await signal_service.generate_signal(request)
    account_state = system_state.get_account_state()
    risk_decision = risk_manager.validate_trade(signal, account_state)

    if not risk_decision.approved:
        return AgentRunResult(
            signal=signal,
            risk_decision=risk_decision,
            execution_result=None,
        )

    try:
        execution_result = executor.execute(signal)
        system_state.register_paper_trade()
    except Exception as exc:
        return AgentRunResult(
            signal=signal,
            risk_decision=RiskDecision(approved=False, reason=f"Execution rejected: {exc}"),
            execution_result=None,
        )

    return AgentRunResult(
        signal=signal,
        risk_decision=risk_decision,
        execution_result=execution_result,
    )

