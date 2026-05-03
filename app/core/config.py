from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Trading AI Agent"
    app_env: str = "development"
    debug: bool = True
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    api_auth_enabled: bool = False
    api_key: str = "replace_me"

    database_url: str = "sqlite:///./trading_agent.db"

    ai_provider: Literal["mock", "openai", "gemini"] = "mock"
    openai_api_key: str = "replace_me"
    openai_model: str = "gpt-4.1-mini"
    gemini_api_key: str = "replace_me"
    gemini_model: str = "gemini-2.5-flash"
    gemini_temperature: float = Field(default=0.1, ge=0, le=2)
    gemini_top_p: float = Field(default=0.9, ge=0, le=1)
    gemini_max_output_tokens: int = Field(default=512, ge=64, le=8192)
    # 0 disables thinking (recommended for JSON classifier — full budget goes
    # to the response). >0 sets an explicit budget. -1 leaves the model default
    # which for 2.5 Flash means dynamic thinking and risks truncated JSON.
    gemini_thinking_budget: int = Field(default=0, ge=-1, le=24576)
    alpha_vantage_api_key: str = "replace_me"

    trading_enabled: bool = True
    paper_trading_enabled: bool = True
    real_trading_enabled: bool = False
    execution_mode: Literal["paper", "binance_testnet", "binance_live"] = "paper"
    trading_market_type: Literal["spot", "futures", "margin"] = "spot"

    market_data_provider: Literal["binance", "context"] = "binance"
    market_data_timeout_seconds: float = Field(default=5, gt=0)
    market_data_kline_limit: int = Field(default=100, ge=30, le=500)
    market_data_price_cache_ttl_seconds: float = Field(default=2, ge=0)

    binance_api_key: str = "replace_me"
    binance_api_secret: str = "replace_me"
    binance_testnet_base_url: str = "https://testnet.binance.vision"
    binance_live_base_url: str = "https://api.binance.com"
    binance_futures_testnet_base_url: str = "https://demo-fapi.binance.com"
    binance_futures_live_base_url: str = "https://fapi.binance.com"
    binance_margin_live_base_url: str = "https://api.binance.com"
    binance_recv_window: int = Field(default=5000, gt=0, le=60000)
    binance_max_retries: int = Field(default=3, ge=0, le=10)
    binance_retry_backoff_seconds: float = Field(default=0.5, ge=0)
    binance_use_test_order_endpoint: bool = False
    binance_order_type: Literal["market", "limit"] = "market"
    binance_limit_time_in_force: Literal["GTC", "IOC", "FOK"] = "IOC"
    binance_futures_position_mode: Literal["one_way", "hedge"] = "one_way"
    binance_margin_isolated: bool = True
    binance_place_oco_protection: bool = False
    binance_stop_limit_slippage_percent: float = Field(default=0.1, ge=0)
    binance_user_stream_enabled: bool = False
    binance_testnet_ws_base_url: str = "wss://testnet.binance.vision/ws"
    binance_live_ws_base_url: str = "wss://stream.binance.com:9443/ws"
    binance_market_stream_enabled: bool = True
    binance_market_stream_base_url: str = "wss://stream.binance.com:9443"
    allowed_symbols: str = "BTCUSDT,ETHUSDT"
    max_notional_per_order: float = Field(default=100, gt=0)

    max_daily_loss: float = Field(default=30, ge=0)
    max_weekly_loss: float = Field(default=80, ge=0)
    max_trades_per_day: int = Field(default=5, ge=0)
    max_risk_per_trade_percent: float = Field(default=1, gt=0)
    min_confidence: float = Field(default=0.55, ge=0, le=1)
    max_signal_price_deviation_percent: float = Field(default=0.5, ge=0)
    default_order_quantity: float = Field(default=0.001, gt=0)

    # Cost modeling. Defaults reflect Binance Spot taker (0.1% / leg) and a
    # conservative slippage assumption for market orders. Round-trip costs are
    # 2x per-leg (entry + exit). Risk-per-trade and R:R checks bake these in
    # so paper-profitable setups must clear real-world friction.
    taker_fee_percent: float = Field(default=0.1, ge=0)
    slippage_assumption_percent: float = Field(default=0.05, ge=0)
    min_reward_to_risk_ratio: float = Field(default=1.5, ge=0)

    kill_switch_enabled: bool = True

    telegram_notifications_enabled: bool = False
    telegram_bot_token: str = "replace_me"
    telegram_chat_id: str = "replace_me"

    autonomous_circuit_breaker_max_consecutive_errors: int = Field(default=5, ge=1)
    autonomous_circuit_breaker_backoff_base_seconds: float = Field(default=1.0, ge=0)
    autonomous_circuit_breaker_backoff_max_seconds: float = Field(default=60.0, ge=0)
    protective_exit_monitor_enabled: bool = True
    protective_exit_monitor_interval_seconds: float = Field(default=1.0, ge=0.2)
    news_risk_enabled: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @model_validator(mode="after")
    def _enforce_production_invariants(self) -> "Settings":
        is_real_mode = (
            self.execution_mode in {"binance_testnet", "binance_live"}
            or self.real_trading_enabled
        )
        if not is_real_mode:
            return self

        if self.database_url.startswith("sqlite"):
            raise ValueError(
                "execution_mode != paper requires a non-SQLite database_url "
                "(use Postgres). SQLite cannot serialize concurrent writes safely."
            )

        if not self.api_auth_enabled:
            raise ValueError(
                "execution_mode != paper requires API_AUTH_ENABLED=true."
            )

        if not self.api_key or self.api_key == "replace_me":
            raise ValueError(
                "execution_mode != paper requires a non-default API_KEY."
            )

        if self.execution_mode == "binance_live" and not self.real_trading_enabled:
            raise ValueError(
                "execution_mode=binance_live requires REAL_TRADING_ENABLED=true."
            )

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
