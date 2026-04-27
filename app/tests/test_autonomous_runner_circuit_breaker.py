import asyncio

import pytest

from app.schemas.agent import AgentTickRequest, AgentTickResult
from app.services.autonomous_runner import AutonomousRunner
from app.services.kill_switch import KillSwitchService


def _result_for(symbol: str) -> AgentTickResult:
    return AgentTickResult(closed_positions=[], run_result=None, reason=f"ok {symbol}")


def test_compute_sleep_uses_interval_when_no_error() -> None:
    runner = AutonomousRunner(
        max_consecutive_errors=5,
        backoff_base_seconds=1.0,
        backoff_max_seconds=60.0,
    )
    runner._interval_seconds = 10.0
    runner._consecutive_errors = 0
    assert runner._compute_sleep(iteration_had_error=False) == 10.0


def test_compute_sleep_grows_exponentially_under_errors() -> None:
    runner = AutonomousRunner(
        max_consecutive_errors=10,
        backoff_base_seconds=1.0,
        backoff_max_seconds=60.0,
    )
    runner._interval_seconds = 1.0
    runner._consecutive_errors = 1
    assert runner._compute_sleep(iteration_had_error=True) == 1.0
    runner._consecutive_errors = 2
    assert runner._compute_sleep(iteration_had_error=True) == 2.0
    runner._consecutive_errors = 3
    assert runner._compute_sleep(iteration_had_error=True) == 4.0


def test_compute_sleep_caps_at_max_seconds() -> None:
    runner = AutonomousRunner(
        max_consecutive_errors=20,
        backoff_base_seconds=1.0,
        backoff_max_seconds=10.0,
    )
    runner._interval_seconds = 1.0
    runner._consecutive_errors = 12
    assert runner._compute_sleep(iteration_had_error=True) == 10.0


def test_circuit_breaker_trips_after_n_errors_and_activates_kill_switch() -> None:
    kill_switch = KillSwitchService(enabled=True)
    kill_switch.deactivate()
    assert kill_switch.is_active() is False

    calls = {"n": 0}

    async def failing_handler(req: AgentTickRequest) -> AgentTickResult:
        calls["n"] += 1
        raise RuntimeError("boom")

    runner = AutonomousRunner(
        kill_switch=kill_switch,
        max_consecutive_errors=3,
        backoff_base_seconds=0.0,
        backoff_max_seconds=0.0,
    )

    async def drive() -> None:
        runner.start(
            symbols=["BTCUSDT"],
            timeframe="1h",
            market_context="ctx",
            interval_seconds=0.0,
            open_new_position=False,
            tick_handler=failing_handler,
        )
        # Wait for the runner to terminate after tripping.
        for _ in range(50):
            if not runner.is_running:
                break
            await asyncio.sleep(0.01)

    asyncio.run(drive())

    status = runner.status()
    assert status["circuit_breaker_tripped"] is True
    assert status["consecutive_errors"] >= 3
    assert calls["n"] >= 3
    assert kill_switch.is_active() is True


def test_consecutive_errors_reset_on_success() -> None:
    kill_switch = KillSwitchService(enabled=True)
    kill_switch.deactivate()

    state = {"calls": 0}

    async def flaky_handler(req: AgentTickRequest) -> AgentTickResult:
        state["calls"] += 1
        if state["calls"] < 3:
            raise RuntimeError("transient")
        # After two failures, succeed forever.
        return _result_for(req.symbol)

    runner = AutonomousRunner(
        kill_switch=kill_switch,
        max_consecutive_errors=5,
        backoff_base_seconds=0.0,
        backoff_max_seconds=0.0,
    )

    async def drive() -> None:
        runner.start(
            symbols=["BTCUSDT"],
            timeframe="1h",
            market_context="ctx",
            interval_seconds=0.0,
            open_new_position=False,
            tick_handler=flaky_handler,
        )
        for _ in range(50):
            if state["calls"] >= 5:
                break
            await asyncio.sleep(0.01)
        await runner.stop()

    asyncio.run(drive())

    status = runner.status()
    assert status["consecutive_errors"] == 0
    assert status["circuit_breaker_tripped"] is False
    assert kill_switch.is_active() is False
