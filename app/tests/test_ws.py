"""Smoke tests for the realtime WebSocket endpoint."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    os.environ["API_AUTH_ENABLED"] = "false"
    from app.core.config import get_settings
    from app.main import app

    get_settings.cache_clear()
    with TestClient(app) as test_client:
        yield test_client


def test_ws_hello_and_audit_event(client: TestClient) -> None:
    with client.websocket_connect("/ws") as websocket:
        hello = websocket.receive_json()
        assert hello["type"] == "hello"

        # Audit logger publishes synchronously via the loop.
        from app.services.audit_logger import AuditLogger

        AuditLogger().record("test_event", {"foo": "bar"})

        # Drain until we see our event (skip any unrelated messages).
        for _ in range(5):
            message = websocket.receive_json()
            if message["type"] == "audit_event":
                assert message["data"]["event_type"] == "test_event"
                assert message["data"]["payload"] == {"foo": "bar"}
                return
        pytest.fail("audit_event was not delivered over the websocket")


def test_ws_pong(client: TestClient) -> None:
    with client.websocket_connect("/ws") as websocket:
        websocket.receive_json()  # hello
        websocket.send_json({"type": "ping"})
        for _ in range(3):
            message = websocket.receive_json()
            if message["type"] == "pong":
                return
        pytest.fail("pong was not received")


def test_ws_rejects_when_auth_enabled_without_key(monkeypatch) -> None:
    monkeypatch.setenv("API_AUTH_ENABLED", "true")
    monkeypatch.setenv("API_KEY", "secret-key")

    from app.core.config import get_settings
    from app.main import app

    get_settings.cache_clear()
    with TestClient(app) as test_client:
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect):
            with test_client.websocket_connect("/ws") as websocket:
                websocket.receive_json()

        with test_client.websocket_connect("/ws?api_key=secret-key") as websocket:
            hello = websocket.receive_json()
            assert hello["type"] == "hello"

    get_settings.cache_clear()
