import asyncio

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_ai_signal_service, get_kill_switch
from app.main import app
from app.providers.ai_provider import AIProvider
from app.schemas.signal import SignalRequest, TradeSignal
from app.services.ai_signal_service import AISignalService


class _CountingProvider(AIProvider):
    def __init__(self) -> None:
        self.calls = 0

    async def generate_signal(self, request: SignalRequest, prompt: str) -> TradeSignal:
        self.calls += 1
        return TradeSignal(
            symbol=request.symbol,
            action="HOLD",
            confidence=0.5,
            risk_amount=0,
            reason="counting provider HOLD",
        )


client = TestClient(app)


def _override(provider: _CountingProvider) -> None:
    app.dependency_overrides[get_ai_signal_service] = lambda: AISignalService(provider=provider)


def _clear_overrides() -> None:
    app.dependency_overrides.pop(get_ai_signal_service, None)


def test_kill_switch_skips_llm_for_autonomous_tick() -> None:
    client.post("/system/simulation/reset")
    get_kill_switch().activate("test")
    provider = _CountingProvider()
    _override(provider)
    try:
        response = client.post(
            "/agent/autonomous/tick",
            json={
                "symbol": "BTCUSDT",
                "timeframe": "1h",
                "market_context": "Precio 64200 alcista.",
            },
        )
    finally:
        _clear_overrides()
        get_kill_switch().deactivate()

    assert response.status_code == 200
    assert provider.calls == 0
    assert "Tick saltado sin llamar a IA" in response.json()["reason"]


def test_kill_switch_skips_llm_for_run_endpoint() -> None:
    client.post("/system/simulation/reset")
    get_kill_switch().activate("test")
    provider = _CountingProvider()
    _override(provider)
    try:
        response = client.post(
            "/agent/run",
            json={
                "symbol": "BTCUSDT",
                "timeframe": "1h",
                "market_context": "Precio 64200 alcista.",
            },
        )
    finally:
        _clear_overrides()
        get_kill_switch().deactivate()

    assert response.status_code == 200
    payload = response.json()
    assert provider.calls == 0
    assert payload["execution_result"] is None
    assert payload["risk_decision"]["approved"] is False
    assert payload["risk_decision"]["reason"] == "Kill switch activo"


def test_existing_position_skips_llm_for_run_endpoint() -> None:
    client.post("/system/simulation/reset")
    provider = _CountingProvider()
    _override(provider)
    try:
        # Open a position first using the default service so the executor sees an OPEN.
        _clear_overrides()
        first = client.post(
            "/agent/run",
            json={
                "symbol": "BTCUSDT",
                "timeframe": "1h",
                "market_context": "Precio 64200 alcista con ruptura y volumen creciente.",
            },
        )
        assert first.status_code == 200
        # Now swap in the counter and try again — must short-circuit without calling LLM.
        _override(provider)
        second = client.post(
            "/agent/run",
            json={
                "symbol": "BTCUSDT",
                "timeframe": "1h",
                "market_context": "Precio 64200 alcista con ruptura y volumen creciente.",
            },
        )
    finally:
        _clear_overrides()

    assert second.status_code == 200
    payload = second.json()
    assert provider.calls == 0
    assert payload["execution_result"] is None
    assert payload["risk_decision"]["reason"] == "Ya existe una posición abierta para el símbolo."
