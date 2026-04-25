from app.services.kill_switch import KillSwitchService


def test_activates_and_stores_reason() -> None:
    service = KillSwitchService(enabled=True)

    status = service.activate("Daily loss reached")

    assert status.active is True
    assert status.reason == "Daily loss reached"
    assert service.is_active() is True


def test_deactivates() -> None:
    service = KillSwitchService(enabled=True)
    service.activate("Manual")

    status = service.deactivate()

    assert status.active is False
    assert status.reason is None

