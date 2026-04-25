import re

import httpx


class MarketService:
    def __init__(
        self,
        provider: str = "binance",
        timeout_seconds: float = 5,
    ) -> None:
        self.provider = provider
        self.timeout_seconds = timeout_seconds

    async def get_current_price(self, symbol: str, market_context: str = "") -> float | None:
        if self.provider == "binance":
            price = await self._get_binance_price(symbol)
            if price is not None:
                return price

        return self.extract_current_price(market_context)

    async def _get_binance_price(self, symbol: str) -> float | None:
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol:
            return None

        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(
                    "https://api.binance.com/api/v3/ticker/price",
                    params={"symbol": normalized_symbol},
                )
                response.raise_for_status()
                payload = response.json()
                return float(payload["price"])
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            return None

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
