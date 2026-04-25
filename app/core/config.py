from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Trading AI Agent"
    app_env: str = "development"
    debug: bool = True

    database_url: str = "sqlite:///./trading_agent.db"

    ai_provider: Literal["mock", "openai", "gemini"] = "mock"
    openai_api_key: str = "replace_me"
    openai_model: str = "gpt-4.1-mini"
    gemini_api_key: str = "replace_me"
    gemini_model: str = "gemini-1.5-pro"

    trading_enabled: bool = True
    paper_trading_enabled: bool = True
    real_trading_enabled: bool = False

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
