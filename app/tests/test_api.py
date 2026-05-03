from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.api.deps import get_news_risk_service
from app.main import app
from app.schemas.news import NewsRiskDecision


client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_agent_run_returns_structured_payload() -> None:
    client.post("/system/simulation/reset")
    response = client.post(
        "/agent/run",
        json={
            "symbol": "BTCUSDT",
            "timeframe": "1h",
            "market_context": "Precio 64200 en tendencia alcista con ruptura y volumen creciente.",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["signal"]["symbol"] == "BTCUSDT"
    assert "approved" in payload["risk_decision"]
    assert payload["execution_result"] is not None
    assert payload["execution_result"]["status"] == "OPEN"


def test_agent_run_rejects_duplicate_open_position() -> None:
    client.post("/system/simulation/reset")
    first_response = client.post(
        "/agent/run",
        json={
            "symbol": "BTCUSDT",
            "timeframe": "1h",
            "market_context": "Precio 64200 en tendencia alcista con ruptura y volumen creciente.",
        },
    )
    second_response = client.post(
        "/agent/run",
        json={
            "symbol": "BTCUSDT",
            "timeframe": "1h",
            "market_context": "Precio 64200 en tendencia alcista con ruptura y volumen creciente.",
        },
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    payload = second_response.json()
    assert payload["execution_result"] is None
    assert payload["risk_decision"]["approved"] is False
    assert payload["risk_decision"]["reason"] == "Ya existe una posición abierta para el símbolo."


def test_autonomous_tick_opens_and_then_closes_position() -> None:
    client.post("/system/simulation/reset")
    opened_response = client.post(
        "/agent/autonomous/tick",
        json={
            "symbol": "BTCUSDT",
            "timeframe": "1h",
            "current_price": 64200,
            "market_context": "Precio 64200 en tendencia alcista con ruptura y volumen creciente.",
        },
    )
    opened_payload = opened_response.json()

    assert opened_response.status_code == 200
    assert opened_payload["run_result"]["execution_result"]["status"] == "OPEN"

    closed_response = client.post(
        "/agent/autonomous/tick",
        json={
            "symbol": "BTCUSDT",
            "timeframe": "1h",
            "current_price": 67000,
            "open_new_position": False,
            "market_context": "Precio 67000 toca take profit.",
        },
    )
    closed_payload = closed_response.json()

    assert closed_response.status_code == 200
    assert len(closed_payload["closed_positions"]) == 1
    assert closed_payload["closed_positions"][0]["status"] == "CLOSED"


def test_autonomous_tick_blocks_new_entry_on_high_news_risk() -> None:
    class BlockingNewsRiskService:
        async def evaluate(self, symbol: str) -> NewsRiskDecision:
            return NewsRiskDecision(
                risk_level="BLOCK",
                action="block_new_entries",
                summary="High-impact news detected.",
                confidence=0.9,
            )

    app.dependency_overrides[get_news_risk_service] = lambda: BlockingNewsRiskService()
    client.post("/system/simulation/reset")
    try:
        response = client.post(
            "/agent/autonomous/tick",
            json={
                "symbol": "BTCUSDT",
                "timeframe": "1h",
                "current_price": 64200,
                "market_context": "Precio 64200 en tendencia alcista.",
            },
        )
    finally:
        app.dependency_overrides.pop(get_news_risk_service, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_result"]["risk_decision"]["approved"] is False
    assert "riesgo de noticias" in payload["reason"]
    assert payload["run_result"]["execution_result"] is None


def test_simulation_reset_is_blocked_outside_paper_mode() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        execution_mode="binance_testnet",
        database_url="postgresql+psycopg://stub:stub@localhost:5432/stub",
        api_auth_enabled=True,
        api_key="secret",
    )
    try:
        response = client.post(
            "/system/simulation/reset", headers={"X-API-Key": "secret"}
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 409
    assert "paper mode" in response.json()["detail"]


def test_protected_routes_require_api_key_when_enabled() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        api_auth_enabled=True,
        api_key="secret",
    )
    try:
        unauthorized = client.get("/system/status")
        authorized = client.get("/system/status", headers={"X-API-Key": "secret"})
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
