import pytest
from pydantic import ValidationError

from app.providers.ai_provider import parse_trade_signal
from app.schemas.signal import TradeSignal


def test_trade_signal_validates_action() -> None:
    with pytest.raises(ValidationError):
        TradeSignal(
            symbol="BTCUSDT",
            action="WAIT",
            confidence=0.7,
            risk_amount=0,
            reason="Invalid action.",
        )


def test_trade_signal_validates_confidence_range() -> None:
    with pytest.raises(ValidationError):
        TradeSignal(
            symbol="BTCUSDT",
            action="HOLD",
            confidence=2,
            risk_amount=0,
            reason="Invalid confidence.",
        )


def test_invalid_ai_json_returns_hold() -> None:
    signal = parse_trade_signal("not-json", symbol="BTCUSDT")

    assert signal.action == "HOLD"
    assert signal.reason.startswith("Invalid AI response")


def test_missing_ai_fields_returns_hold() -> None:
    signal = parse_trade_signal({"symbol": "BTCUSDT", "action": "BUY"}, symbol="BTCUSDT")

    assert signal.action == "HOLD"
    assert signal.reason.startswith("Invalid AI response")

