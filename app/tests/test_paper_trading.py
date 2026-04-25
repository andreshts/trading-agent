import pytest

from app.schemas.signal import TradeSignal
from app.services.paper_trading import PaperTradingExecutor


def make_signal(action: str = "BUY") -> TradeSignal:
    stop_loss = 62800 if action != "SELL" else 65600
    take_profit = 67000 if action != "SELL" else 62000
    return TradeSignal(
        symbol="BTCUSDT",
        action=action,
        confidence=0.72,
        entry_price=64200,
        stop_loss=stop_loss,
        take_profit=take_profit,
        risk_amount=10,
        reason="Valid setup.",
    )


def test_simulates_buy() -> None:
    result = PaperTradingExecutor().execute(make_signal("BUY"))

    assert result.status == "OPEN"
    assert result.action == "BUY"
    assert result.id is not None


def test_simulates_sell() -> None:
    result = PaperTradingExecutor().execute(make_signal("SELL"))

    assert result.status == "OPEN"
    assert result.action == "SELL"


def test_rejects_hold() -> None:
    with pytest.raises(ValueError, match="HOLD signals cannot be executed"):
        PaperTradingExecutor().execute(make_signal("HOLD"))


def test_rejects_real_trading_enabled() -> None:
    with pytest.raises(RuntimeError, match="Real trading is disabled"):
        PaperTradingExecutor(real_trading_enabled=True).execute(make_signal("BUY"))


def test_closes_buy_with_profit() -> None:
    executor = PaperTradingExecutor(default_order_quantity=0.001)
    opened = executor.execute(make_signal("BUY"))

    closed = executor.close_position(opened.id, exit_price=65200, exit_reason="take_profit")

    assert closed.status == "CLOSED"
    assert closed.realized_pnl == pytest.approx(1)
