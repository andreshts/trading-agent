import pytest

from app.schemas.signal import TradeSignal
from app.schemas.system import AccountState
from app.services.kill_switch import KillSwitchService
from app.services.risk_manager import RiskManager


def make_manager(kill_switch: KillSwitchService | None = None) -> RiskManager:
    return RiskManager(
        max_daily_loss=30,
        max_weekly_loss=80,
        max_trades_per_day=5,
        max_risk_per_trade_percent=1,
        min_confidence=0.55,
        kill_switch=kill_switch or KillSwitchService(enabled=True),
        default_order_quantity=0.001,
    )


def make_signal(**overrides) -> TradeSignal:
    data = {
        "symbol": "BTCUSDT",
        "action": "BUY",
        "confidence": 0.72,
        "entry_price": 64200,
        "stop_loss": 62800,
        "take_profit": 67000,
        "risk_amount": 10,
        "reason": "Valid setup.",
    }
    data.update(overrides)
    return TradeSignal(**data)


def make_account(**overrides) -> AccountState:
    data = {
        "equity": 1000,
        "daily_loss": 0,
        "weekly_loss": 0,
        "trades_today": 0,
        "trading_enabled": True,
    }
    data.update(overrides)
    return AccountState(**data)


def test_approves_valid_trade() -> None:
    decision = make_manager().validate_trade(make_signal(), make_account())

    assert decision.approved is True
    assert decision.risk_amount == pytest.approx(1.4)


def test_rejects_daily_loss_limit() -> None:
    kill_switch = KillSwitchService(enabled=True)
    decision = make_manager(kill_switch).validate_trade(make_signal(), make_account(daily_loss=30))

    assert decision.approved is False
    assert decision.reason == "Límite de pérdida diaria alcanzado"
    assert kill_switch.is_active() is True


def test_rejects_weekly_loss_limit() -> None:
    decision = make_manager().validate_trade(make_signal(), make_account(weekly_loss=80))

    assert decision.approved is False
    assert decision.reason == "Límite de pérdida semanal alcanzado"


def test_rejects_max_daily_trades() -> None:
    decision = make_manager().validate_trade(make_signal(), make_account(trades_today=5))

    assert decision.approved is False
    assert decision.reason == "Máximo de operaciones diarias alcanzado"


def test_rejects_buy_without_stop_loss() -> None:
    decision = make_manager().validate_trade(make_signal(stop_loss=None), make_account())

    assert decision.approved is False
    assert decision.reason == "Operación bloqueada: no tiene stop loss"


def test_rejects_sell_without_stop_loss() -> None:
    decision = make_manager().validate_trade(
        make_signal(action="SELL", stop_loss=None),
        make_account(),
    )

    assert decision.approved is False
    assert decision.reason == "Operación bloqueada: no tiene stop loss"


def test_rejects_risk_above_allowed_percent() -> None:
    decision = make_manager().validate_trade(make_signal(risk_amount=0), make_account(equity=1000), quantity=0.01)

    assert decision.approved is False
    assert decision.reason == "Riesgo por operación superior al 1%"


def test_ignores_ai_risk_amount_and_calculates_in_backend() -> None:
    decision = make_manager().validate_trade(
        make_signal(risk_amount=9999),
        make_account(equity=1000),
    )

    assert decision.approved is True
    assert decision.risk_amount == pytest.approx(1.4)


def test_rejects_buy_with_stop_loss_above_entry() -> None:
    decision = make_manager().validate_trade(
        make_signal(stop_loss=65000),
        make_account(),
    )

    assert decision.approved is False
    assert decision.reason == "BUY inválido: stop_loss debe estar por debajo de entry_price"


def test_rejects_sell_with_stop_loss_below_entry() -> None:
    decision = make_manager().validate_trade(
        make_signal(action="SELL", stop_loss=63000, take_profit=62000),
        make_account(),
    )

    assert decision.approved is False
    assert decision.reason == "SELL inválido: stop_loss debe estar por encima de entry_price"


def test_rejects_active_kill_switch() -> None:
    kill_switch = KillSwitchService(enabled=True)
    kill_switch.activate("Manual")

    decision = make_manager(kill_switch).validate_trade(make_signal(), make_account())

    assert decision.approved is False
    assert decision.reason == "Trading bloqueado por kill switch"


def test_rejects_low_confidence() -> None:
    decision = make_manager().validate_trade(make_signal(confidence=0.2), make_account())

    assert decision.approved is False
    assert decision.reason == "Confianza inferior al mínimo permitido"
