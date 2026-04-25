from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_paper_executor
from app.api.deps import get_system_state
from app.schemas.trade import ClosePositionRequest, PaperPosition, PaperTradeRequest, PaperTradeResult
from app.services.paper_trading import PaperTradingExecutor
from app.services.system_state import SystemStateService


router = APIRouter()


@router.post("/paper", response_model=PaperTradeResult)
async def execute_paper_trade(
    request: PaperTradeRequest,
    executor: PaperTradingExecutor = Depends(get_paper_executor),
) -> PaperTradeResult:
    try:
        return executor.execute(request.signal, quantity=request.quantity)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/positions", response_model=list[PaperPosition])
async def list_positions(
    status: str | None = Query(default=None, pattern="^(OPEN|CLOSED|open|closed)$"),
    limit: int = Query(default=100, ge=1, le=500),
    executor: PaperTradingExecutor = Depends(get_paper_executor),
) -> list[PaperPosition]:
    return executor.list_positions(status=status, limit=limit)


@router.post("/positions/{position_id}/close", response_model=PaperPosition)
async def close_position(
    position_id: int,
    request: ClosePositionRequest,
    executor: PaperTradingExecutor = Depends(get_paper_executor),
    system_state: SystemStateService = Depends(get_system_state),
) -> PaperPosition:
    try:
        position = executor.close_position(
            position_id=position_id,
            exit_price=request.exit_price,
            exit_reason=request.exit_reason,
        )
        system_state.register_closed_position(position.realized_pnl or 0)
        return position
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
