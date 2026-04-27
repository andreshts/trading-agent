import asyncio
import time

import pytest

from app.services.binance_market_stream import (
    BinanceMarketDataStream,
    get_market_stream,
    set_market_stream,
)
from app.services.market_service import MarketService


@pytest.fixture(autouse=True)
def clear_singleton():
    set_market_stream(None)
    yield
    set_market_stream(None)


def test_handle_event_updates_last_price_from_mini_ticker() -> None:
    stream = BinanceMarketDataStream(symbols=["BTCUSDT"])
    stream.handle_event(
        {
            "stream": "btcusdt@miniTicker",
            "data": {"e": "24hrMiniTicker", "s": "BTCUSDT", "c": "65000.50"},
        }
    )
    assert stream.get_last_price("BTCUSDT") == pytest.approx(65000.50)


def test_handle_event_updates_book_ticker() -> None:
    stream = BinanceMarketDataStream(symbols=["BTCUSDT"])
    stream.handle_event(
        {
            "stream": "btcusdt@bookTicker",
            "data": {"s": "BTCUSDT", "b": "64000.10", "a": "64001.20"},
        }
    )
    assert stream.get_bid("BTCUSDT") == pytest.approx(64000.10)
    assert stream.get_ask("BTCUSDT") == pytest.approx(64001.20)
    # last_price falls back to mid when only book is seen
    assert stream.get_last_price("BTCUSDT") == pytest.approx(64000.65)


def test_handle_event_ignores_unknown_symbol() -> None:
    stream = BinanceMarketDataStream(symbols=["BTCUSDT"])
    stream.handle_event({"data": {"s": "ETHUSDT", "c": "3000"}})
    assert stream.get_last_price("ETHUSDT") is None
    assert stream.get_last_price("BTCUSDT") is None


def test_get_last_price_respects_max_age() -> None:
    stream = BinanceMarketDataStream(symbols=["BTCUSDT"])
    stream.handle_event({"data": {"s": "BTCUSDT", "c": "1"}})
    # Force the quote to look stale.
    stream._quotes["BTCUSDT"].received_at = time.monotonic() - 10.0
    assert stream.get_last_price("BTCUSDT", max_age_seconds=1.0) is None
    assert stream.get_last_price("BTCUSDT") == pytest.approx(1.0)


def test_market_service_prefers_stream_cache_over_rest() -> None:
    stream = BinanceMarketDataStream(symbols=["BTCUSDT"])
    stream.handle_event({"data": {"s": "BTCUSDT", "c": "70000"}})
    set_market_stream(stream)

    service = MarketService(provider="binance")

    async def call() -> float | None:
        # If the stream has a fresh price, this returns immediately without REST.
        return await service.get_current_price("BTCUSDT")

    price = asyncio.run(call())
    assert price == pytest.approx(70000.0)


def test_market_service_falls_back_when_stream_stale() -> None:
    stream = BinanceMarketDataStream(symbols=["BTCUSDT"])
    stream.handle_event({"data": {"s": "BTCUSDT", "c": "70000"}})
    stream._quotes["BTCUSDT"].received_at = time.monotonic() - 60.0
    set_market_stream(stream)

    service = MarketService(provider="context")  # avoids REST in the test

    async def call() -> float | None:
        return await service.get_current_price("BTCUSDT", market_context="Precio 71500.")

    price = asyncio.run(call())
    # provider != binance, so it goes straight to extract_current_price
    assert price == pytest.approx(71500.0)


def test_singleton_set_and_get() -> None:
    assert get_market_stream() is None
    stream = BinanceMarketDataStream(symbols=["BTCUSDT"])
    set_market_stream(stream)
    assert get_market_stream() is stream
