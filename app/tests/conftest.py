import os

import pytest


os.environ["EXECUTION_MODE"] = "paper"
os.environ["AI_PROVIDER"] = "mock"
os.environ["MARKET_DATA_PROVIDER"] = "context"


@pytest.fixture(autouse=True)
def reset_kill_switch_state():
    from app.services.kill_switch import KillSwitchService

    KillSwitchService(enabled=True).deactivate()
    yield
