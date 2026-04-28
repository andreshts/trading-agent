"""Async pub/sub event bus used to broadcast realtime events to WebSocket clients.

The bus is a process-wide singleton. It is safe to publish from synchronous code,
from asyncio coroutines, or from threads other than the one running the loop.

Subscribers receive events through their own ``asyncio.Queue``; a slow consumer
will not block other subscribers — when its queue is full, the oldest pending
message is dropped to make room for the new one (best-effort delivery).
"""

from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

# Audit event_type -> resources the frontend should refresh.
_AUDIT_RESOURCE_HINTS: dict[str, list[str]] = {
    "paper_trade": ["positions", "status"],
    "paper_position_closed": ["positions", "status"],
    "binance_order_placed": ["positions", "status"],
    "binance_user_stream_position_closed": ["positions", "status"],
    "autonomous_runner_started": ["runner", "status"],
    "autonomous_runner_stopped": ["runner", "status"],
    "autonomous_runner_error": ["runner"],
    "autonomous_runner_tick": ["runner"],
    "kill_switch_activated": ["status"],
    "kill_switch_deactivated": ["status"],
    "risk_config_updated": ["status", "limits"],
    "risk_config_reset": ["status", "limits"],
}


class EventBus:
    """In-memory async pub/sub bus.

    Lifecycle:
        bus.bind_loop(asyncio.get_running_loop())  # once at app startup
        queue = await bus.subscribe()              # per WS connection
        bus.publish("event_type", {...})           # any code path
        await bus.unsubscribe(queue)               # on disconnect
    """

    def __init__(self, max_queue_size: int = 200) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._max_queue_size = max_queue_size

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def has_subscribers(self) -> bool:
        return bool(self._subscribers)

    async def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._max_queue_size)
        self._subscribers.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def publish(self, event_type: str, data: Any) -> None:
        """Thread-safe, non-blocking publish."""
        if not self._subscribers:
            return
        message = {"type": event_type, "data": data}
        loop = self._loop
        if loop is None:
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            self._dispatch(message)
        else:
            try:
                loop.call_soon_threadsafe(self._dispatch, message)
            except RuntimeError:
                logger.debug("EventBus loop unavailable, dropping %s", event_type)

    def publish_resources_changed(self, resources: list[str]) -> None:
        """Hint the frontend to re-fetch one or more REST resources."""
        if not resources:
            return
        self.publish("resources_changed", {"resources": list(dict.fromkeys(resources))})

    def publish_audit(self, event: dict[str, Any]) -> None:
        """Publish an audit event plus any implied resource hints."""
        self.publish("audit_event", event)
        hints = _AUDIT_RESOURCE_HINTS.get(event.get("event_type", ""), [])
        if hints:
            self.publish_resources_changed(hints)

    def _dispatch(self, message: dict) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                # Drop oldest to make room — best-effort delivery for slow clients.
                try:
                    queue.get_nowait()
                    queue.put_nowait(message)
                except Exception:  # pragma: no cover - defensive
                    logger.warning("Dropping event for saturated subscriber.")


@lru_cache
def get_event_bus() -> EventBus:
    return EventBus()
