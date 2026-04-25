from fastapi import APIRouter, Depends

from app.api.deps import get_risk_manager
from app.schemas.risk import RiskDecision, RiskLimits, RiskValidationRequest
from app.services.risk_manager import RiskManager


router = APIRouter()


@router.post("/validate", response_model=RiskDecision)
async def validate_trade(
    request: RiskValidationRequest,
    risk_manager: RiskManager = Depends(get_risk_manager),
) -> RiskDecision:
    return risk_manager.validate_trade(request.signal, request.account_state)


@router.get("/limits", response_model=RiskLimits)
async def get_limits(risk_manager: RiskManager = Depends(get_risk_manager)) -> RiskLimits:
    return RiskLimits(
        max_daily_loss=risk_manager.max_daily_loss,
        max_weekly_loss=risk_manager.max_weekly_loss,
        max_trades_per_day=risk_manager.max_trades_per_day,
        max_risk_per_trade_percent=risk_manager.max_risk_per_trade_percent,
        min_confidence=risk_manager.min_confidence,
    )

