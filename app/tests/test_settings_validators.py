import pytest

from app.core.config import Settings


def _kwargs(**overrides) -> dict:
    base = {
        "execution_mode": "binance_testnet",
        "database_url": "postgresql+psycopg://u:p@h:5432/db",
        "api_auth_enabled": True,
        "api_key": "real-secret",
        "real_trading_enabled": False,
    }
    base.update(overrides)
    return base


def test_paper_mode_with_sqlite_is_allowed() -> None:
    Settings(execution_mode="paper", database_url="sqlite:///./x.db")


def test_real_mode_rejects_sqlite() -> None:
    with pytest.raises(ValueError, match="non-SQLite"):
        Settings(**_kwargs(database_url="sqlite:///./x.db"))


def test_real_mode_rejects_disabled_api_auth() -> None:
    with pytest.raises(ValueError, match="API_AUTH_ENABLED"):
        Settings(**_kwargs(api_auth_enabled=False))


def test_real_mode_rejects_default_api_key() -> None:
    with pytest.raises(ValueError, match="API_KEY"):
        Settings(**_kwargs(api_key="replace_me"))


def test_live_mode_requires_real_trading_enabled_flag() -> None:
    with pytest.raises(ValueError, match="REAL_TRADING_ENABLED"):
        Settings(**_kwargs(execution_mode="binance_live", real_trading_enabled=False))


def test_real_mode_with_proper_config_is_accepted() -> None:
    Settings(**_kwargs())
