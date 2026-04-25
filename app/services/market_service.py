import re


class MarketService:
    @staticmethod
    def extract_current_price(market_context: str) -> float | None:
        match = re.search(r"\d+(?:[.,]\d+)?", market_context)
        if not match:
            return None
        return float(match.group(0).replace(",", "."))
