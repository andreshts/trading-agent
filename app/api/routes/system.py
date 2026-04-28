from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError

from app.api.deps import get_audit_logger, get_kill_switch, get_system_state
from app.core.config import Settings, get_settings
from app.schemas.risk import RiskConfig, RiskConfigUpdate
from app.schemas.system import AccountState, KillSwitchRequest, KillSwitchStatus, SystemStatus
from app.services.audit_logger import AuditLogger
from app.services.kill_switch import KillSwitchService
from app.services.runtime_config import ALLOWED_KEYS, RuntimeConfigStore, get_runtime_config_store
from app.services.system_state import SystemStateService


router = APIRouter()


@router.get("/status", response_model=SystemStatus)
async def get_status(
    settings: Settings = Depends(get_settings),
    kill_switch: KillSwitchService = Depends(get_kill_switch),
    system_state: SystemStateService = Depends(get_system_state),
    audit_logger: AuditLogger = Depends(get_audit_logger),
) -> SystemStatus:
    account_state = system_state.get_account_state()
    return SystemStatus(
        app_name=settings.app_name,
        app_env=settings.app_env,
        execution_mode=settings.execution_mode,
        trading_enabled=account_state.trading_enabled and not kill_switch.is_active(),
        paper_trading_enabled=settings.paper_trading_enabled,
        real_trading_enabled=settings.real_trading_enabled,
        exchange_configured=(
            settings.binance_api_key != "replace_me"
            and settings.binance_api_secret != "replace_me"
        ),
        allowed_symbols=[
            symbol.strip().upper()
            for symbol in settings.allowed_symbols.split(",")
            if symbol.strip()
        ],
        max_notional_per_order=settings.max_notional_per_order,
        kill_switch=kill_switch.get_status(),
        audit_events=audit_logger.count(),
        account=account_state,
    )


@router.get("/account", response_model=AccountState)
async def get_account_state(
    system_state: SystemStateService = Depends(get_system_state),
) -> AccountState:
    return system_state.get_account_state()


@router.post("/kill-switch/activate", response_model=KillSwitchStatus)
async def activate_kill_switch(
    request: KillSwitchRequest,
    kill_switch: KillSwitchService = Depends(get_kill_switch),
) -> KillSwitchStatus:
    return kill_switch.activate(request.reason)


@router.post("/kill-switch/deactivate", response_model=KillSwitchStatus)
async def deactivate_kill_switch(
    kill_switch: KillSwitchService = Depends(get_kill_switch),
) -> KillSwitchStatus:
    return kill_switch.deactivate()


@router.post("/trading/disable", response_model=AccountState)
async def disable_trading(
    system_state: SystemStateService = Depends(get_system_state),
) -> AccountState:
    return system_state.set_trading_enabled(False)


@router.post("/trading/enable", response_model=AccountState)
async def enable_trading(
    system_state: SystemStateService = Depends(get_system_state),
) -> AccountState:
    return system_state.set_trading_enabled(True)


@router.post("/simulation/reset", response_model=AccountState)
async def reset_simulation(
    settings: Settings = Depends(get_settings),
    system_state: SystemStateService = Depends(get_system_state),
) -> AccountState:
    if settings.execution_mode != "paper":
        raise HTTPException(
            status_code=409,
            detail=(
                "Simulation reset is only available in paper mode. "
                "Close exchange positions before clearing local state."
            ),
        )
    return system_state.reset_simulation()


@router.get("/audit")
async def list_audit_events(
    limit: int = Query(default=100, ge=1, le=500),
    audit_logger: AuditLogger = Depends(get_audit_logger),
) -> list[dict]:
    return audit_logger.list_events(limit=limit)


def _risk_config_from_settings(settings: Settings) -> RiskConfig:
    return RiskConfig(**{key: getattr(settings, key) for key in ALLOWED_KEYS})


@router.get("/risk-config", response_model=RiskConfig)
async def get_risk_config(settings: Settings = Depends(get_settings)) -> RiskConfig:
    return _risk_config_from_settings(settings)


@router.post("/risk-config", response_model=RiskConfig)
async def update_risk_config(
    update: RiskConfigUpdate,
    settings: Settings = Depends(get_settings),
    audit_logger: AuditLogger = Depends(get_audit_logger),
    store: RuntimeConfigStore = Depends(get_runtime_config_store),
) -> RiskConfig:
    partial = update.model_dump(exclude_unset=True, exclude_none=True)
    if not partial:
        return _risk_config_from_settings(settings)
    try:
        applied = store.update(settings, partial)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    audit_logger.record("risk_config_updated", {"changes": partial, "applied": applied})
    return _risk_config_from_settings(settings)


@router.post("/risk-config/reset", response_model=RiskConfig)
async def reset_risk_config(
    settings: Settings = Depends(get_settings),
    audit_logger: AuditLogger = Depends(get_audit_logger),
    store: RuntimeConfigStore = Depends(get_runtime_config_store),
) -> RiskConfig:
    store.clear(settings)
    audit_logger.record("risk_config_reset", {})
    return _risk_config_from_settings(settings)
