import pytest

from app.services.binance_market_stream import (
    BinanceMarketDataStream,
    set_market_stream,
)
from app.services.binance_spot import BinanceSpotExecutor
from app.tests.test_binance_spot_executor import FakeBinanceClient, make_signal


@pytest.fixture(autouse=True)
def clear_singleton():
    set_market_stream(None)
    yield
    set_market_stream(None)


def make_executor(client: FakeBinanceClient | None = None) -> BinanceSpotExecutor:
    return BinanceSpotExecutor(
        client=client or FakeBinanceClient(),
        execution_mode="binance_testnet",
        real_trading_enabled=False,
        default_order_quantity=0.001,
        allowed_symbols=["BTCUSDT"],
        max_notional_per_order=100,
        order_type="market",
        max_signal_price_deviation_percent=0.5,
    )


def test_executor_passes_when_stream_price_close_to_signal() -> None:
    stream = BinanceMarketDataStream(symbols=["BTCUSDT"])
    # Signal entry 64200, ask 64200.5 -> 0.0008% deviation, well under 0.5%.
    stream.handle_event({"data": {"s": "BTCUSDT", "b": "64199.5", "a": "64200.5"}})
    set_market_stream(stream)

    executor = make_executor()
    result = executor.execute(make_signal("BUY"), intent_id="ok-intent")
    assert result.exchange_order_id is not None


def test_executor_rejects_when_stream_price_drifted_beyond_threshold() -> None:
    stream = BinanceMarketDataStream(symbols=["BTCUSDT"])
    # Signal entry 64200, ask 65000 -> ~1.2% deviation > 0.5%.
    stream.handle_event({"data": {"s": "BTCUSDT", "b": "64999", "a": "65000"}})
    set_market_stream(stream)

    executor = make_executor()
    with pytest.raises(RuntimeError, match="Pre-POST price re-check rejected"):
        executor.execute(make_signal("BUY"), intent_id="drift-intent")


def test_executor_does_not_block_when_stream_unavailable() -> None:
    set_market_stream(None)
    executor = make_executor()
    # Without a stream, behavior matches pre-WS world: order goes through.
    result = executor.execute(make_signal("BUY"), intent_id="no-stream-intent")
    assert result.exchange_order_id is not None
