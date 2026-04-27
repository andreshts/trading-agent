"""Realtime WebSocket endpoint for the dashboard.

Auth: when ``api_auth_enabled`` is true, the client must send the configured key
either as the ``api_key`` query parameter (the only portable option for browsers)
or as the ``X-API-Key`` header.

Protocol (server -> client):
    {"type": "hello",             "data": {"server_time": ...}}
    {"type": "audit_event",       "data": {timestamp, event_type, payload}}
    {"type": "resources_changed", "data": {"resources": ["status", "positions", ...]}}
    {"type": "position_prices",   "data": {"prices": {"BTCUSDT": 12345.6}}}
    {"type": "ping",              "data": {"ts": ...}}

Protocol (client -> server):
    {"type": "ping"}   # optional keepalive; server replies with pong
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.core.config import get_settings
from app.services.event_bus import get_event_bus

logger = logging.getLogger(__name__)

router = APIRouter()

HEARTBEAT_SECONDS = 20.0


def _is_authorized(provided: str | None) -> bool:
    settings = get_settings()
    if not settings.api_auth_enabled:
        return True
    if not settings.api_key or settings.api_key == "replace_me":
        return False
    return provided == settings.api_key


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    api_key: str | None = Query(default=None),
) -> None:
    provided = api_key or websocket.headers.get("x-api-key")
    if not _is_authorized(provided):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    bus = get_event_bus()
    queue = await bus.subscribe()

    await websocket.send_json(
        {
            "type": "hello",
            "data": {"server_time": datetime.now(timezone.utc).isoformat()},
        }
    )

    sender = asyncio.create_task(_sender_loop(websocket, queue), name="ws-sender")
    receiver = asyncio.create_task(_receiver_loop(websocket), name="ws-receiver")
    heartbeat = asyncio.create_task(_heartbeat_loop(websocket), name="ws-heartbeat")

    try:
        done, pending = await asyncio.wait(
            {sender, receiver, heartbeat},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc and not isinstance(exc, (WebSocketDisconnect, asyncio.CancelledError)):
                logger.debug("ws task ended with %s", exc)
    finally:
        await bus.unsubscribe(queue)
        try:
            await websocket.close()
        except Exception:
            pass


async def _sender_loop(websocket: WebSocket, queue: asyncio.Queue) -> None:
    while True:
        message = await queue.get()
        await websocket.send_json(message)


async def _receiver_loop(websocket: WebSocket) -> None:
    while True:
        try:
            message = await websocket.receive_json()
        except WebSocketDisconnect:
            return
        except Exception:
            # Ignore malformed frames, keep the connection alive.
            continue
        if isinstance(message, dict) and message.get("type") == "ping":
            await websocket.send_json(
                {"type": "pong", "data": {"ts": datetime.now(timezone.utc).isoformat()}}
            )


async def _heartbeat_loop(websocket: WebSocket) -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        await websocket.send_json(
            {"type": "ping", "data": {"ts": datetime.now(timezone.utc).isoformat()}}
        )
