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
        return self.get_status()

    def deactivate(self) -> KillSwitchStatus:
        self._active = False
        self._reason = None
        return self.get_status()

    def is_active(self) -> bool:
        return self.enabled and self._active

    def get_status(self) -> KillSwitchStatus:
        return KillSwitchStatus(enabled=self.enabled, active=self.is_active(), reason=self._reason)

