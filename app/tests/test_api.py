from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_agent_run_returns_structured_payload() -> None:
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
    assert payload["execution_result"]["status"] == "simulated"

