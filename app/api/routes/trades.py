from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_paper_executor
from app.schemas.trade import PaperTradeRequest, PaperTradeResult
from app.services.paper_trading import PaperTradingExecutor


router = APIRouter()


@router.post("/paper", response_model=PaperTradeResult)
async def execute_paper_trade(
    request: PaperTradeRequest,
    executor: PaperTradingExecutor = Depends(get_paper_executor),
) -> PaperTradeResult:
    try:
        return executor.execute(request.signal)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

