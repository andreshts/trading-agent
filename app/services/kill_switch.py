from app.db.models import KillSwitchEvent
from app.db.session import SessionLocal
from app.schemas.system import KillSwitchStatus


class KillSwitchService:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._active = False
        self._reason: str | None = None

    def activate(self, reason: str) -> KillSwitchStatus:
        if self.enabled:
            self._active = True
            self._reason = reason
            self._record("activate", reason)
        return self.get_status()

    def deactivate(self) -> KillSwitchStatus:
        self._active = False
        self._reason = None
        self._record("deactivate", None)
        return self.get_status()

    def is_active(self) -> bool:
        return self.enabled and self._active

    def get_status(self) -> KillSwitchStatus:
        return KillSwitchStatus(enabled=self.enabled, active=self.is_active(), reason=self._reason)

    @staticmethod
    def _record(action: str, reason: str | None) -> None:
        with SessionLocal() as db:
            db.add(KillSwitchEvent(action=action, reason=reason, payload={}))
            db.commit()
