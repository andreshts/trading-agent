import asyncio

import pytest

from app.core.config import Settings
from app.schemas.signal import TradeSignal
from app.services.binance_market_stream import BinanceMarketDataStream, set_market_stream
from app.services.market_service import MarketService
from app.services.paper_trading import PaperTradingExecutor
from app.services.protective_exit_monitor import evaluate_protective_exits
from app.services.system_state import SystemStateService


@pytest.fixture(autouse=True)
def clear_market_stream():
    set_market_stream(None)
    yield
    set_market_stream(None)


def test_protective_exit_monitor_closes_take_profit_without_dashboard_subscriber() -> None:
    system_state = SystemStateService(Settings())
    system_state.reset_simulation()
    executor = PaperTradingExecutor()
    opened = executor.execute(
        TradeSignal(
            symbol="BTCUSDT",
            action="BUY",
            confidence=0.8,
            entry_price=64200,
            stop_loss=62800,
            take_profit=67000,
            reason="Valid setup.",
        )
    )
    system_state.register_paper_trade()

    stream = BinanceMarketDataStream(symbols=["BTCUSDT"])
    stream.handle_event({"data": {"s": "BTCUSDT", "b": "67010", "a": "67012"}})
    set_market_stream(stream)

    result = asyncio.run(
        evaluate_protective_exits(
            executor=executor,
            market_service=MarketService(provider="binance"),
            system_state=system_state,
        )
    )

    assert result.prices["BTCUSDT"] == pytest.approx(67010)
    assert len(result.closed_positions) == 1
    assert result.closed_positions[0].id == opened.id
    assert result.closed_positions[0].exit_reason == "take_profit"
    assert result.closed_positions[0].exit_price == pytest.approx(67010)
