import pytest

from app.schemas.signal import TradeSignal
from app.services.paper_trading import PaperTradingExecutor


def make_signal(action: str = "BUY") -> TradeSignal:
    return TradeSignal(
        symbol="BTCUSDT",
        action=action,
        confidence=0.72,
        entry_price=64200,
        stop_loss=62800,
        take_profit=67000,
        risk_amount=10,
        reason="Valid setup.",
    )


def test_simulates_buy() -> None:
    result = PaperTradingExecutor().execute(make_signal("BUY"))

    assert result.status == "simulated"
    assert result.action == "BUY"


def test_simulates_sell() -> None:
    result = PaperTradingExecutor().execute(make_signal("SELL"))

    assert result.status == "simulated"
    assert result.action == "SELL"


def test_rejects_hold() -> None:
    with pytest.raises(ValueError, match="HOLD signals cannot be executed"):
        PaperTradingExecutor().execute(make_signal("HOLD"))


def test_rejects_real_trading_enabled() -> None:
    with pytest.raises(RuntimeError, match="Real trading is disabled"):
        PaperTradingExecutor(real_trading_enabled=True).execute(make_signal("BUY"))

