from datetime import datetime, timezone
from typing import Any


class AuditLogger:
    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []

    def record(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "payload": payload,
        }
        self._events.append(event)
        return event

    def list_events(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._events[-limit:]

    def count(self) -> int:
        return len(self._events)

