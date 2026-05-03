from functools import lru_cache

from app.core.config import Settings, get_settings
from app.providers.ai_provider import AIProvider
from app.providers.gemini_provider import GeminiProvider
from app.providers.mock_provider import MockAIProvider
from app.providers.openai_provider import OpenAIProvider
from app.services.ai_signal_service import AISignalService
from app.services.audit_logger import AuditLogger
from app.services.autonomous_runner import AutonomousRunner
from app.services.binance_spot import BinanceSpotClient, BinanceSpotExecutor
from app.services.binance_multi_market import (
    BinanceFuturesClient,
    BinanceFuturesExecutor,
    BinanceMarginClient,
    BinanceMarginExecutor,
)
from app.services.kill_switch import KillSwitchService
from app.services.market_service import MarketService
from app.services.news_risk_service import AlphaVantageNewsProvider, NewsRiskService
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
        return GeminiProvider(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            temperature=settings.gemini_temperature,
            top_p=settings.gemini_top_p,
            max_output_tokens=settings.gemini_max_output_tokens,
            thinking_budget=settings.gemini_thinking_budget,
        )
    return MockAIProvider()


def get_ai_signal_service() -> AISignalService:
    settings = get_settings()
    return AISignalService(
        provider=get_ai_provider(settings),
        audit_logger=get_audit_logger(),
        min_reward_to_risk_ratio=settings.min_reward_to_risk_ratio,
    )


def get_risk_manager() -> RiskManager:
    settings = get_settings()
    return RiskManager(
        max_daily_loss=settings.max_daily_loss,
        max_weekly_loss=settings.max_weekly_loss,
        max_trades_per_day=settings.max_trades_per_day,
        max_risk_per_trade_percent=settings.max_risk_per_trade_percent,
        min_confidence=settings.min_confidence,
        max_signal_price_deviation_percent=settings.max_signal_price_deviation_percent,
        default_order_quantity=settings.default_order_quantity,
        taker_fee_percent=settings.taker_fee_percent,
        slippage_assumption_percent=settings.slippage_assumption_percent,
        min_reward_to_risk_ratio=settings.min_reward_to_risk_ratio,
        kill_switch=get_kill_switch(),
        audit_logger=get_audit_logger(),
    )


def get_market_service() -> MarketService:
    settings = get_settings()
    return MarketService(
        provider=settings.market_data_provider,
        timeout_seconds=settings.market_data_timeout_seconds,
        kline_limit=settings.market_data_kline_limit,
        price_cache_ttl_seconds=settings.market_data_price_cache_ttl_seconds,
    )


@lru_cache
def get_news_risk_service() -> NewsRiskService:
    settings = get_settings()
    provider = AlphaVantageNewsProvider(api_key=settings.alpha_vantage_api_key)
    return NewsRiskService(
        provider=provider,
        enabled=settings.news_risk_enabled and provider.configured,
        audit_logger=get_audit_logger(),
    )


@lru_cache
def get_autonomous_runner() -> AutonomousRunner:
    settings = get_settings()
    return AutonomousRunner(
        audit_logger=get_audit_logger(),
        kill_switch=get_kill_switch(),
        max_consecutive_errors=settings.autonomous_circuit_breaker_max_consecutive_errors,
        backoff_base_seconds=settings.autonomous_circuit_breaker_backoff_base_seconds,
        backoff_max_seconds=settings.autonomous_circuit_breaker_backoff_max_seconds,
    )


def get_paper_executor() -> PaperTradingExecutor:
    settings = get_settings()
    if settings.execution_mode in {"binance_testnet", "binance_live"}:
        allowed_symbols = [
            symbol.strip().upper()
            for symbol in settings.allowed_symbols.split(",")
            if symbol.strip()
        ]
        common = {
            "execution_mode": settings.execution_mode,
            "real_trading_enabled": settings.real_trading_enabled,
            "default_order_quantity": settings.default_order_quantity,
            "allowed_symbols": allowed_symbols,
            "max_notional_per_order": settings.max_notional_per_order,
            "order_type": settings.binance_order_type,
            "limit_time_in_force": settings.binance_limit_time_in_force,
            "use_test_order_endpoint": settings.binance_use_test_order_endpoint,
            "audit_logger": get_audit_logger(),
        }
        if settings.trading_market_type == "futures":
            base_url = (
                settings.binance_futures_testnet_base_url
                if settings.execution_mode == "binance_testnet"
                else settings.binance_futures_live_base_url
            )
            return BinanceFuturesExecutor(
                client=BinanceFuturesClient(
                    api_key=settings.binance_api_key,
                    api_secret=settings.binance_api_secret,
                    base_url=base_url,
                    recv_window=settings.binance_recv_window,
                    max_retries=settings.binance_max_retries,
                    retry_backoff_seconds=settings.binance_retry_backoff_seconds,
                ),
                position_mode=settings.binance_futures_position_mode,
                **common,
            )

        if settings.trading_market_type == "margin":
            return BinanceMarginExecutor(
                client=BinanceMarginClient(
                    api_key=settings.binance_api_key,
                    api_secret=settings.binance_api_secret,
                    base_url=settings.binance_margin_live_base_url,
                    recv_window=settings.binance_recv_window,
                    max_retries=settings.binance_max_retries,
                    retry_backoff_seconds=settings.binance_retry_backoff_seconds,
                ),
                isolated=settings.binance_margin_isolated,
                **common,
            )

        base_url = (
            settings.binance_testnet_base_url
            if settings.execution_mode == "binance_testnet"
            else settings.binance_live_base_url
        )
        spot_common = dict(common)
        spot_common.pop("use_test_order_endpoint")
        return BinanceSpotExecutor(
            client=BinanceSpotClient(
                api_key=settings.binance_api_key,
                api_secret=settings.binance_api_secret,
                base_url=base_url,
                recv_window=settings.binance_recv_window,
                max_retries=settings.binance_max_retries,
                retry_backoff_seconds=settings.binance_retry_backoff_seconds,
            ),
            place_oco_protection=settings.binance_place_oco_protection,
            stop_limit_slippage_percent=settings.binance_stop_limit_slippage_percent,
            use_test_order_endpoint=settings.binance_use_test_order_endpoint,
            max_signal_price_deviation_percent=settings.max_signal_price_deviation_percent,
            **spot_common,
        )

    return PaperTradingExecutor(
        paper_trading_enabled=settings.paper_trading_enabled,
        real_trading_enabled=settings.real_trading_enabled,
        default_order_quantity=settings.default_order_quantity,
        taker_fee_percent=settings.taker_fee_percent,
        slippage_assumption_percent=settings.slippage_assumption_percent,
        audit_logger=get_audit_logger(),
    )
