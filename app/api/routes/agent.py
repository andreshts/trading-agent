from fastapi import APIRouter, Depends

from app.api.deps import (
    get_ai_signal_service,
    get_market_service,
    get_paper_executor,
    get_risk_manager,
    get_system_state,
)
from app.schemas.agent import AgentRunResult, AgentTickRequest, AgentTickResult
from app.schemas.risk import RiskDecision
from app.schemas.signal import SignalRequest, TradeSignal
from app.services.ai_signal_service import AISignalService
from app.services.market_service import MarketService
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
        execution_result = executor.execute(
            signal,
            quantity=risk_decision.quantity,
            risk_amount=risk_decision.risk_amount,
        )
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


@router.post("/autonomous/tick", response_model=AgentTickResult)
async def autonomous_tick(
    request: AgentTickRequest,
    signal_service: AISignalService = Depends(get_ai_signal_service),
    risk_manager: RiskManager = Depends(get_risk_manager),
    executor: PaperTradingExecutor = Depends(get_paper_executor),
    system_state: SystemStateService = Depends(get_system_state),
    market_service: MarketService = Depends(get_market_service),
) -> AgentTickResult:
    current_price = request.current_price
    if current_price is None:
        current_price = await market_service.get_current_price(request.symbol, request.market_context)

    closed_positions = []

    if current_price is not None:
        closed_positions = executor.evaluate_open_positions(request.symbol, current_price)
        for position in closed_positions:
            system_state.register_closed_position(position.realized_pnl or 0)

    if not request.open_new_position:
        return AgentTickResult(
            closed_positions=closed_positions,
            run_result=None,
            reason="Tick procesado sin apertura de nueva posición.",
        )

    if executor.has_open_position(request.symbol):
        return AgentTickResult(
            closed_positions=closed_positions,
            run_result=None,
            reason="Ya existe una posición abierta para el símbolo.",
        )

    enriched_request = request.model_copy(
        update={
            "market_context": MarketService.with_current_price_context(
                request.market_context,
                current_price,
            )
        }
    )
    signal = await signal_service.generate_signal(enriched_request)
    account_state = system_state.get_account_state()
    risk_decision = risk_manager.validate_trade(signal, account_state)

    if not risk_decision.approved:
        return AgentTickResult(
            closed_positions=closed_positions,
            run_result=AgentRunResult(
                signal=signal,
                risk_decision=risk_decision,
                execution_result=None,
            ),
            reason="Señal rechazada por RiskManager.",
        )

    try:
        execution_result = executor.execute(
            signal,
            quantity=risk_decision.quantity,
            risk_amount=risk_decision.risk_amount,
        )
        system_state.register_paper_trade()
    except Exception as exc:
        risk_decision = RiskDecision(approved=False, reason=f"Execution rejected: {exc}")
        execution_result = None

    return AgentTickResult(
        closed_positions=closed_positions,
        run_result=AgentRunResult(
            signal=signal,
            risk_decision=risk_decision,
            execution_result=execution_result,
        ),
        reason="Tick autónomo procesado.",
    )
