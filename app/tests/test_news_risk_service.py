import asyncio

from app.services.news_risk_service import NewsRiskService


class FakeNewsProvider:
    def __init__(self, items):
        self.items = items
        self.calls = 0

    async def fetch_news(self, symbol: str, lookback_minutes: int):
        self.calls += 1
        return self.items


def test_news_risk_blocks_high_impact_headline() -> None:
    provider = FakeNewsProvider(
        [
            {
                "title": "SEC lawsuit triggers Bitcoin volatility",
                "summary": "Regulator action affects crypto markets.",
                "time_published": "29990101T000000",
                "overall_sentiment_score": "-0.12",
                "url": "https://example.com/news",
            }
        ]
    )
    service = NewsRiskService(provider=provider)

    decision = asyncio.run(service.evaluate("BTCUSDT"))

    assert decision.action == "block_new_entries"
    assert decision.risk_level == "BLOCK"
    assert "SEC lawsuit" in decision.summary


def test_news_risk_allows_when_no_high_impact_headlines() -> None:
    provider = FakeNewsProvider(
        [
            {
                "title": "Bitcoin trades sideways",
                "summary": "Market remains quiet.",
                "time_published": "29990101T000000",
                "overall_sentiment_score": "0.01",
            }
        ]
    )
    service = NewsRiskService(provider=provider)

    decision = asyncio.run(service.evaluate("BTCUSDT"))

    assert decision.action == "allow"
    assert decision.risk_level == "LOW"


def test_news_risk_uses_cache() -> None:
    provider = FakeNewsProvider([])
    service = NewsRiskService(provider=provider, cache_ttl_seconds=300)

    asyncio.run(service.evaluate("BTCUSDT"))
    asyncio.run(service.evaluate("BTCUSDT"))

    assert provider.calls == 1


def test_news_risk_fails_open_when_provider_errors() -> None:
    class BrokenProvider:
        async def fetch_news(self, symbol: str, lookback_minutes: int):
            raise RuntimeError("upstream unavailable")

    service = NewsRiskService(provider=BrokenProvider())

    decision = asyncio.run(service.evaluate("BTCUSDT"))

    assert decision.action == "allow"
    assert decision.risk_level == "UNKNOWN"
