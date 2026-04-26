from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Trading AI Agent"
    app_env: str = "development"
    debug: bool = True
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    database_url: str = "sqlite:///./trading_agent.db"

    ai_provider: Literal["mock", "openai", "gemini"] = "mock"
    openai_api_key: str = "replace_me"
    openai_model: str = "gpt-4.1-mini"
    gemini_api_key: str = "replace_me"
    gemini_model: str = "gemini-1.5-pro"

    trading_enabled: bool = True
    paper_trading_enabled: bool = True
    real_trading_enabled: bool = False
    execution_mode: Literal["paper", "binance_testnet", "binance_live"] = "paper"

    market_data_provider: Literal["binance", "context"] = "binance"
    market_data_timeout_seconds: float = Field(default=5, gt=0)
    market_data_kline_limit: int = Field(default=100, ge=30, le=500)

    binance_api_key: str = "replace_me"
    binance_api_secret: str = "replace_me"
    binance_testnet_base_url: str = "https://testnet.binance.vision"
    binance_live_base_url: str = "https://api.binance.com"
    binance_recv_window: int = Field(default=5000, gt=0, le=60000)
    binance_use_test_order_endpoint: bool = False
    allowed_symbols: str = "BTCUSDT,ETHUSDT"
    max_notional_per_order: float = Field(default=100, gt=0)

    max_daily_loss: float = Field(default=30, ge=0)
    max_weekly_loss: float = Field(default=80, ge=0)
    max_trades_per_day: int = Field(default=5, ge=0)
    max_risk_per_trade_percent: float = Field(default=1, gt=0)
    min_confidence: float = Field(default=0.55, ge=0, le=1)
    default_order_quantity: float = Field(default=0.001, gt=0)

    kill_switch_enabled: bool = True

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
