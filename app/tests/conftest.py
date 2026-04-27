import os
import tempfile

import pytest


os.environ["EXECUTION_MODE"] = "paper"
os.environ["REAL_TRADING_ENABLED"] = "false"
os.environ["AI_PROVIDER"] = "mock"
os.environ["MARKET_DATA_PROVIDER"] = "context"
os.environ["API_AUTH_ENABLED"] = "false"
os.environ["DATABASE_URL"] = (
    f"sqlite:///{tempfile.gettempdir()}/trading_agent_test.db"
)


@pytest.fixture(autouse=True)
def reset_kill_switch_state():
    from app.services.kill_switch import KillSwitchService

    KillSwitchService(enabled=True).deactivate()
    yield
