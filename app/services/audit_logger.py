from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.db.models import AuditEvent
from app.db.session import SessionLocal, init_db


class AuditLogger:
    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []
        init_db()

    def record(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "payload": payload,
        }
        self._events.append(event)
        try:
            with SessionLocal() as db:
                db.add(AuditEvent(event_type=event_type, payload=payload))
                db.commit()
        except Exception:
            pass
        return event

    def list_events(self, limit: int = 100) -> list[dict[str, Any]]:
        try:
            with SessionLocal() as db:
                rows = db.scalars(
                    select(AuditEvent).order_by(AuditEvent.timestamp.desc()).limit(limit)
                ).all()
                return [
                    {
                        "timestamp": row.timestamp.isoformat(),
                        "event_type": row.event_type,
                        "payload": row.payload,
                    }
                    for row in rows
                ]
        except Exception:
            return self._events[-limit:]

    def count(self) -> int:
        try:
            with SessionLocal() as db:
                return len(db.scalars(select(AuditEvent.id)).all())
        except Exception:
            return len(self._events)
