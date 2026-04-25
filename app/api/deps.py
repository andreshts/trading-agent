from functools import lru_cache

from app.core.config import Settings, get_settings
from app.providers.ai_provider import AIProvider
from app.providers.gemini_provider import GeminiProvider
from app.providers.mock_provider import MockAIProvider
from app.providers.openai_provider import OpenAIProvider
from app.services.ai_signal_service import AISignalService
from app.services.audit_logger import AuditLogger
from app.services.kill_switch import KillSwitchService
from app.services.paper_trading import PaperTradingExecutor
from app.services.risk_manager import RiskManager
from app.services.system_state import SystemStateService


@lru_cache
def get_audit_logger() -> AuditLogger:
    return AuditLogger()


@lru_cache
def get_kill_switch() -> KillSwitchService:
    settings = get_settings()
    return KillSwitchService(enabled=settings.kill_switch_enabled)


@lru_cache
def get_system_state() -> SystemStateService:
    return SystemStateService(settings=get_settings())


def get_ai_provider(settings: Settings | None = None) -> AIProvider:
    settings = settings or get_settings()
    if settings.ai_provider == "openai":
        return OpenAIProvider(api_key=settings.openai_api_key, model=settings.openai_model)
    if settings.ai_provider == "gemini":
        return GeminiProvider(api_key=settings.gemini_api_key, model=settings.gemini_model)
    return MockAIProvider()


def get_ai_signal_service() -> AISignalService:
    return AISignalService(provider=get_ai_provider(), audit_logger=get_audit_logger())


def get_risk_manager() -> RiskManager:
    settings = get_settings()
    return RiskManager(
        max_daily_loss=settings.max_daily_loss,
        max_weekly_loss=settings.max_weekly_loss,
        max_trades_per_day=settings.max_trades_per_day,
        max_risk_per_trade_percent=settings.max_risk_per_trade_percent,
        min_confidence=settings.min_confidence,
        kill_switch=get_kill_switch(),
        audit_logger=get_audit_logger(),
    )


def get_paper_executor() -> PaperTradingExecutor:
    settings = get_settings()
    return PaperTradingExecutor(
        paper_trading_enabled=settings.paper_trading_enabled,
        real_trading_enabled=settings.real_trading_enabled,
        audit_logger=get_audit_logger(),
    )
