"""Public Binance market data WebSocket.

Replaces the per-tick REST polling for last price / book ticker. We connect
once to wss://stream.binance.com/stream and multiplex all ALLOWED_SYMBOLS,
caching the latest price / bid / ask per symbol in memory.

Consumers (MarketService, the price ticker fan-out, the pre-POST risk
re-check) read from this in-process cache instead of hitting REST. REST
remains as a cold-start fallback for symbols the stream has not pushed yet
and for klines which are historical.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import websockets


logger = logging.getLogger(__name__)


@dataclass
class SymbolQuote:
    last_price: float | None = None
    bid_price: float | None = None
    ask_price: float | None = None
    received_at: float = 0.0


class BinanceMarketDataStream:
    def __init__(
        self,
        symbols: list[str],
        ws_base_url: str = "wss://stream.binance.com:9443",
        reconnect_seconds: float = 3.0,
    ) -> None:
        self.symbols = [s.strip().upper() for s in symbols if s.strip()]
        self.ws_base_url = ws_base_url.rstrip("/")
        self.reconnect_seconds = reconnect_seconds
        self._quotes: dict[str, SymbolQuote] = {sym: SymbolQuote() for sym in self.symbols}
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def get_last_price(self, symbol: str, max_age_seconds: float | None = None) -> float | None:
        return self._read("last_price", symbol, max_age_seconds)

    def get_bid(self, symbol: str, max_age_seconds: float | None = None) -> float | None:
        return self._read("bid_price", symbol, max_age_seconds)

    def get_ask(self, symbol: str, max_age_seconds: float | None = None) -> float | None:
        return self._read("ask_price", symbol, max_age_seconds)

    def snapshot(self) -> dict[str, dict[str, float | None]]:
        return {
            symbol: {
                "last_price": q.last_price,
                "bid_price": q.bid_price,
                "ask_price": q.ask_price,
                "age_seconds": (time.monotonic() - q.received_at) if q.received_at else None,
            }
            for symbol, q in self._quotes.items()
        }

    async def start(self) -> None:
        if self.is_running or not self.symbols:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(), name="binance-market-stream")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def _run(self) -> None:
        url = self._build_url()
        while not self._stop_event.is_set():
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
                    async for raw_message in ws:
                        if self._stop_event.is_set():
                            break
                        try:
                            self.handle_event(json.loads(raw_message))
                        except Exception:
                            logger.exception("market stream parse error")
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("market stream connection error")
                await asyncio.sleep(self.reconnect_seconds)

    def handle_event(self, event: dict[str, Any]) -> None:
        # Combined-stream payload wraps the inner event under "data"
        data = event.get("data", event)
        symbol = str(data.get("s") or "").upper()
        if not symbol or symbol not in self._quotes:
            return

        # miniTicker (e == "24hrMiniTicker"): last close in "c"
        # bookTicker (no "e"): best bid "b" and best ask "a"
        last_price = self._as_float(data.get("c"))
        bid_price = self._as_float(data.get("b"))
        ask_price = self._as_float(data.get("a"))

        quote = self._quotes[symbol]
        if last_price is not None:
            quote.last_price = last_price
        if bid_price is not None:
            quote.bid_price = bid_price
        if ask_price is not None:
            quote.ask_price = ask_price
        if last_price is None and bid_price is not None and ask_price is not None:
            quote.last_price = (bid_price + ask_price) / 2
        quote.received_at = time.monotonic()

    def _build_url(self) -> str:
        streams: list[str] = []
        for symbol in self.symbols:
            lower = symbol.lower()
            streams.append(f"{lower}@miniTicker")
            streams.append(f"{lower}@bookTicker")
        return f"{self.ws_base_url}/stream?streams={'/'.join(streams)}"

    def _read(
        self,
        attr: str,
        symbol: str,
        max_age_seconds: float | None,
    ) -> float | None:
        quote = self._quotes.get(symbol.strip().upper())
        if quote is None:
            return None
        value = getattr(quote, attr)
        if value is None or quote.received_at == 0.0:
            return None
        if max_age_seconds is not None:
            if time.monotonic() - quote.received_at > max_age_seconds:
                return None
        return value

    @staticmethod
    def _as_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


_singleton: BinanceMarketDataStream | None = None


def set_market_stream(stream: BinanceMarketDataStream | None) -> None:
    global _singleton
    _singleton = stream


def get_market_stream() -> BinanceMarketDataStream | None:
    return _singleton
