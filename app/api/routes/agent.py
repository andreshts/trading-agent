from fastapi import APIRouter, Depends

from app.api.deps import (
    get_ai_signal_service,
    get_autonomous_runner,
    get_market_service,
    get_paper_executor,
    get_risk_manager,
    get_system_state,
)
from app.schemas.agent import (
    AgentRunResult,
    AgentTickRequest,
    AgentTickResult,
    AutonomousRunnerStatus,
    AutonomousStartRequest,
)
from app.schemas.risk import RiskDecision
from app.schemas.signal import SignalRequest, TradeSignal
from app.services.ai_signal_service import AISignalService
from app.services.autonomous_runner import AutonomousRunner
from app.services.market_service import MarketService
from app.services.paper_trading import PaperTradingExecutor
from app.services.risk_manager import RiskManager
from app.services.system_state import SystemStateService


router = APIRouter()


def account_state_for_risk(
    system_state: SystemStateService,
    executor: PaperTradingExecutor,
):
    account_state = system_state.get_account_state()
    if hasattr(executor, "get_account_state"):
        return executor.get_account_state(account_state)
    return account_state


async def enrich_signal_request(
    request: SignalRequest,
    market_service: MarketService,
) -> SignalRequest:
    market_context = await market_service.build_analysis_context(
        symbol=request.symbol,
        timeframe=request.timeframe,
        market_context=request.market_context,
    )
    return request.model_copy(update={"market_context": market_context})


async def process_autonomous_tick(
    request: AgentTickRequest,
    signal_service: AISignalService,
    risk_manager: RiskManager,
    executor: PaperTradingExecutor,
    system_state: SystemStateService,
    market_service: MarketService,
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

    enriched_request = await enrich_signal_request(request, market_service)
    signal = await signal_service.generate_signal(enriched_request)
    account_state = account_state_for_risk(system_state, executor)
    risk_decision = risk_manager.validate_trade(signal, account_state, market_price=current_price)

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


@router.post("/signal", response_model=TradeSignal)
async def generate_signal(
    request: SignalRequest,
    signal_service: AISignalService = Depends(get_ai_signal_service),
    market_service: MarketService = Depends(get_market_service),
) -> TradeSignal:
    enriched_request = await enrich_signal_request(request, market_service)
    return await signal_service.generate_signal(enriched_request)


@router.post("/run", response_model=AgentRunResult)
async def run_agent(
    request: SignalRequest,
    signal_service: AISignalService = Depends(get_ai_signal_service),
    risk_manager: RiskManager = Depends(get_risk_manager),
    executor: PaperTradingExecutor = Depends(get_paper_executor),
    system_state: SystemStateService = Depends(get_system_state),
    market_service: MarketService = Depends(get_market_service),
) -> AgentRunResult:
    enriched_request = await enrich_signal_request(request, market_service)
    signal = await signal_service.generate_signal(enriched_request)

    if executor.has_open_position(signal.symbol):
        return AgentRunResult(
            signal=signal,
            risk_decision=RiskDecision(
                approved=False,
                reason="Ya existe una posición abierta para el símbolo.",
            ),
            execution_result=None,
        )

    market_price = await market_service.get_current_price(request.symbol, request.market_context)
    account_state = account_state_for_risk(system_state, executor)
    risk_decision = risk_manager.validate_trade(signal, account_state, market_price=market_price)

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
    return await process_autonomous_tick(
        request=request,
        signal_service=signal_service,
        risk_manager=risk_manager,
        executor=executor,
        system_state=system_state,
        market_service=market_service,
    )


@router.post("/autonomous/start", response_model=AutonomousRunnerStatus)
async def start_autonomous_runner(
    request: AutonomousStartRequest,
    runner: AutonomousRunner = Depends(get_autonomous_runner),
    signal_service: AISignalService = Depends(get_ai_signal_service),
    risk_manager: RiskManager = Depends(get_risk_manager),
    executor: PaperTradingExecutor = Depends(get_paper_executor),
    system_state: SystemStateService = Depends(get_system_state),
    market_service: MarketService = Depends(get_market_service),
) -> AutonomousRunnerStatus:
    async def tick_handler(tick_request: AgentTickRequest) -> AgentTickResult:
        return await process_autonomous_tick(
            request=tick_request,
            signal_service=signal_service,
            risk_manager=risk_manager,
            executor=executor,
            system_state=system_state,
            market_service=market_service,
        )

    return AutonomousRunnerStatus.model_validate(
        runner.start(
            symbols=request.symbols,
            timeframe=request.timeframe,
            market_context=request.market_context,
            interval_seconds=request.interval_seconds,
            open_new_position=request.open_new_position,
            tick_handler=tick_handler,
        )
    )


@router.post("/autonomous/stop", response_model=AutonomousRunnerStatus)
async def stop_autonomous_runner(
    runner: AutonomousRunner = Depends(get_autonomous_runner),
) -> AutonomousRunnerStatus:
    return AutonomousRunnerStatus.model_validate(await runner.stop())


@router.get("/autonomous/status", response_model=AutonomousRunnerStatus)
async def get_autonomous_runner_status(
    runner: AutonomousRunner = Depends(get_autonomous_runner),
) -> AutonomousRunnerStatus:
    return AutonomousRunnerStatus.model_validate(runner.status())
