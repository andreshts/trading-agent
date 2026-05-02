import re
import time
from statistics import mean

import httpx

from app.services.binance_market_stream import get_market_stream


class MarketService:
    def __init__(
        self,
        provider: str = "binance",
        timeout_seconds: float = 5,
        kline_limit: int = 100,
        price_cache_ttl_seconds: float = 2,
    ) -> None:
        self.provider = provider
        self.timeout_seconds = timeout_seconds
        self.kline_limit = kline_limit
        self.price_cache_ttl_seconds = price_cache_ttl_seconds
        self._price_cache: dict[str, tuple[float, float]] = {}

    async def get_current_price(self, symbol: str, market_context: str = "") -> float | None:
        if self.provider == "binance":
            stream_price = self._get_stream_price(symbol)
            if stream_price is not None:
                return stream_price
            price = await self._get_binance_price(symbol)
            if price is not None:
                return price

        return self.extract_current_price(market_context)

    def get_book_ticker(self, symbol: str) -> tuple[float | None, float | None]:
        stream = get_market_stream()
        if stream is None:
            return None, None
        return stream.get_bid(symbol), stream.get_ask(symbol)

    async def get_exit_reference_price(
        self,
        symbol: str,
        action: str = "BUY",
    ) -> float | None:
        """Return the price a protective close would realistically cross.

        BUY positions close by selling, so bid is the first usable trigger.
        SELL positions close by buying, so ask is the first usable trigger.
        """
        if self.provider == "binance":
            stream = get_market_stream()
            if stream is not None:
                normalized_action = action.strip().upper()
                if normalized_action == "BUY":
                    price = stream.get_bid(symbol, max_age_seconds=5.0)
                else:
                    price = stream.get_ask(symbol, max_age_seconds=5.0)
                if price is not None:
                    return price
        return await self.get_current_price(symbol)

    @staticmethod
    def _get_stream_price(symbol: str) -> float | None:
        stream = get_market_stream()
        if stream is None:
            return None
        # 5s freshness window: if the stream went silent we let REST take over
        # rather than serve a stale price for risk decisions.
        return stream.get_last_price(symbol, max_age_seconds=5.0)

    async def build_analysis_context(
        self,
        symbol: str,
        timeframe: str,
        market_context: str,
    ) -> str:
        current_price = await self.get_current_price(symbol, market_context)
        if self.provider != "binance":
            return self.with_current_price_context(market_context, current_price)

        candles = self._closed_candles(await self._get_binance_klines(symbol, timeframe))
        if not candles:
            return self.with_current_price_context(market_context, current_price)

        summary = self.summarize_candles(candles, current_price=current_price)
        if not summary:
            return self.with_current_price_context(market_context, current_price)

        return "\n".join(
            [
                summary,
                "",
                "Criterio del usuario:",
                market_context.strip(),
            ]
        ).strip()

    async def _get_binance_price(self, symbol: str) -> float | None:
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol:
            return None
        cached = self._price_cache.get(normalized_symbol)
        now = time.monotonic()
        if cached and now - cached[0] <= self.price_cache_ttl_seconds:
            return cached[1]

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(
                    "https://api.binance.com/api/v3/ticker/price",
                    params={"symbol": normalized_symbol},
                )
                response.raise_for_status()
                payload = response.json()
                price = float(payload["price"])
                self._price_cache[normalized_symbol] = (now, price)
                return price
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            return None

    async def _get_binance_klines(self, symbol: str, timeframe: str) -> list[dict]:
        normalized_symbol = symbol.strip().upper()
        interval = self._normalize_binance_interval(timeframe)
        if not normalized_symbol or interval is None:
            return []

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(
                    "https://api.binance.com/api/v3/klines",
                    params={
                        "symbol": normalized_symbol,
                        "interval": interval,
                        "limit": self.kline_limit,
                    },
                )
                response.raise_for_status()
                return [self._parse_kline(row) for row in response.json()]
        except (httpx.HTTPError, TypeError, ValueError):
            return []

    @staticmethod
    def _parse_kline(row: list) -> dict:
        return {
            "open_time": int(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
            "close_time": int(row[6]),
        }

    @staticmethod
    def _closed_candles(candles: list[dict], now_ms: int | None = None) -> list[dict]:
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        return [candle for candle in candles if candle.get("close_time", 0) <= now_ms]

    @staticmethod
    def summarize_candles(candles: list[dict], current_price: float | None = None) -> str:
        if len(candles) < 30:
            return ""

        closes = [candle["close"] for candle in candles]
        highs = [candle["high"] for candle in candles]
        lows = [candle["low"] for candle in candles]
        volumes = [candle["volume"] for candle in candles]
        last_close = closes[-1]
        price = current_price or last_close
        ema_9 = MarketService._ema(closes, 9)
        ema_21 = MarketService._ema(closes, 21)
        ema_50 = MarketService._ema(closes, 50)
        rsi_14 = MarketService._rsi(closes, 14)
        high_20 = max(highs[-20:])
        low_20 = min(lows[-20:])
        avg_volume_20 = mean(volumes[-20:])
        volume_ratio = volumes[-1] / avg_volume_20 if avg_volume_20 else 0
        change_1 = MarketService._percent_change(closes[-2], price)
        change_3 = MarketService._percent_change(closes[-4], price)
        change_12 = MarketService._percent_change(closes[-13], price)

        trend = "neutral"
        if ema_9 > ema_21 > ema_50 and price > ema_21:
            trend = "alcista"
        elif ema_9 < ema_21 < ema_50 and price < ema_21:
            trend = "bajista"

        return "\n".join(
            [
                "Datos de mercado calculados desde Binance.",
                f"Precio actual: {price:.8g}.",
                f"Velas analizadas: {len(candles)}.",
                f"EMA 9: {ema_9:.8g}; EMA 21: {ema_21:.8g}; EMA 50: {ema_50:.8g}; tendencia EMA: {trend}.",
                f"RSI 14: {rsi_14:.2f}.",
                f"Cambio 1 vela: {change_1:.2f}%; cambio 3 velas: {change_3:.2f}%; cambio 12 velas: {change_12:.2f}%.",
                f"Maximo 20 velas: {high_20:.8g}; minimo 20 velas: {low_20:.8g}.",
                f"Volumen actual: {volumes[-1]:.8g}; volumen promedio 20 velas: {avg_volume_20:.8g}; ratio volumen: {volume_ratio:.2f}.",
                "Usa estos datos para decidir BUY, SELL o HOLD. Si no hay ventaja clara, responde HOLD.",
            ]
        )

    @staticmethod
    def _normalize_binance_interval(timeframe: str) -> str | None:
        normalized = timeframe.strip().lower()
        aliases = {
            "1m": "1m",
            "3m": "3m",
            "5m": "5m",
            "15m": "15m",
            "30m": "30m",
            "1h": "1h",
            "2h": "2h",
            "4h": "4h",
            "6h": "6h",
            "8h": "8h",
            "12h": "12h",
            "1d": "1d",
            "3d": "3d",
            "1w": "1w",
        }
        return aliases.get(normalized)

    @staticmethod
    def _ema(values: list[float], period: int) -> float:
        if not values:
            return 0
        multiplier = 2 / (period + 1)
        ema = values[0]
        for value in values[1:]:
            ema = (value - ema) * multiplier + ema
        return ema

    @staticmethod
    def _rsi(values: list[float], period: int = 14) -> float:
        if len(values) <= period:
            return 50

        gains = []
        losses = []
        for previous, current in zip(values[-period - 1 : -1], values[-period:]):
            change = current - previous
            gains.append(max(change, 0))
            losses.append(abs(min(change, 0)))

        avg_gain = mean(gains)
        avg_loss = mean(losses)
        if avg_loss == 0:
            return 100
        relative_strength = avg_gain / avg_loss
        return 100 - (100 / (1 + relative_strength))

    @staticmethod
    def _percent_change(previous: float, current: float) -> float:
        if previous == 0:
            return 0
        return ((current - previous) / previous) * 100

    @staticmethod
    def extract_current_price(market_context: str) -> float | None:
        match = re.search(r"\d+(?:[.,]\d+)?", market_context)
        if not match:
            return None
        return float(match.group(0).replace(",", "."))

    @staticmethod
    def with_current_price_context(market_context: str, current_price: float | None) -> str:
        if current_price is None:
            return market_context
        return f"{market_context}\nPrecio actual de mercado: {current_price}."
