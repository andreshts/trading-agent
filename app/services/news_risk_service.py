from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import httpx

from app.schemas.news import NewsRiskDecision, NewsSource
from app.services.audit_logger import AuditLogger


class NewsProvider(Protocol):
    async def fetch_news(self, symbol: str, lookback_minutes: int) -> list[dict[str, Any]]:
        ...


class AlphaVantageNewsProvider:
    def __init__(
        self,
        api_key: str,
        timeout_seconds: float = 8.0,
        base_url: str = "https://www.alphavantage.co/query",
    ) -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.base_url = base_url

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.api_key != "replace_me")

    async def fetch_news(self, symbol: str, lookback_minutes: int) -> list[dict[str, Any]]:
        if not self.configured:
            return []
        params = {
            "function": "NEWS_SENTIMENT",
            "tickers": self._alpha_vantage_ticker(symbol),
            "topics": "blockchain,financial_markets,economy_macro,economy_monetary",
            "time_from": self._time_from(lookback_minutes),
            "sort": "LATEST",
            "limit": "20",
            "apikey": self.api_key,
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.get(self.base_url, params=params)
            response.raise_for_status()
            payload = response.json()
        feed = payload.get("feed")
        return feed if isinstance(feed, list) else []

    @staticmethod
    def _alpha_vantage_ticker(symbol: str) -> str:
        normalized = symbol.upper()
        if normalized.endswith("USDT"):
            base = normalized.removesuffix("USDT")
            return f"CRYPTO:{base}"
        if normalized.endswith("USD"):
            base = normalized.removesuffix("USD")
            return f"CRYPTO:{base}"
        return normalized

    @staticmethod
    def _time_from(lookback_minutes: int) -> str:
        value = datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)
        return value.strftime("%Y%m%dT%H%M")


class NewsRiskService:
    HIGH_IMPACT_KEYWORDS = {
        "bankruptcy",
        "ban",
        "breach",
        "cftc",
        "crackdown",
        "cpi",
        "default",
        "delist",
        "etf",
        "exploit",
        "fed",
        "fomc",
        "hack",
        "inflation",
        "investigation",
        "lawsuit",
        "liquidation",
        "outage",
        "rate cut",
        "rate hike",
        "regulation",
        "regulator",
        "sec",
        "seized",
        "settlement",
        "stablecoin",
        "sues",
        "suspends",
    }

    def __init__(
        self,
        provider: NewsProvider,
        enabled: bool = True,
        lookback_minutes: int = 90,
        cache_ttl_seconds: int = 300,
        audit_logger: AuditLogger | None = None,
    ) -> None:
        self.provider = provider
        self.enabled = enabled
        self.lookback_minutes = lookback_minutes
        self.cache_ttl_seconds = cache_ttl_seconds
        self.audit_logger = audit_logger
        self._cache: dict[str, tuple[float, NewsRiskDecision]] = {}

    async def evaluate(self, symbol: str) -> NewsRiskDecision:
        normalized_symbol = symbol.upper()
        if not self.enabled:
            return NewsRiskDecision(enabled=False, risk_level="UNKNOWN", summary="News risk disabled.")

        cached = self._cache.get(normalized_symbol)
        now = time.monotonic()
        if cached and now - cached[0] <= self.cache_ttl_seconds:
            return cached[1]

        try:
            items = await self.provider.fetch_news(normalized_symbol, self.lookback_minutes)
            decision = self._classify(items)
        except Exception as exc:
            decision = NewsRiskDecision(
                risk_level="UNKNOWN",
                action="allow",
                summary=f"News risk unavailable; allowing entries: {exc}",
                confidence=0,
            )

        self._cache[normalized_symbol] = (now, decision)
        if self.audit_logger:
            self.audit_logger.record(
                "news_risk_decision",
                {"symbol": normalized_symbol, **decision.model_dump(mode="json")},
            )
        return decision

    def _classify(self, items: list[dict[str, Any]]) -> NewsRiskDecision:
        relevant = [item for item in items if self._is_recent(item)]
        high_impact = [item for item in relevant if self._is_high_impact(item)]
        if not high_impact:
            return NewsRiskDecision(
                risk_level="LOW",
                action="allow",
                summary="No high-impact crypto or macro headlines in the news lookback window.",
                confidence=0.3 if relevant else 0.1,
                sources=[self._source(item) for item in relevant[:3]],
            )

        sources = [self._source(item) for item in high_impact[:3]]
        titles = "; ".join(source.title for source in sources)
        return NewsRiskDecision(
            risk_level="BLOCK",
            action="block_new_entries",
            summary=f"High-impact news detected: {titles}",
            confidence=min(0.95, 0.65 + (0.1 * len(high_impact))),
            sources=sources,
        )

    def _is_recent(self, item: dict[str, Any]) -> bool:
        published = self._published_at(item)
        if published is None:
            return True
        threshold = datetime.now(timezone.utc) - timedelta(minutes=self.lookback_minutes)
        return published >= threshold

    def _is_high_impact(self, item: dict[str, Any]) -> bool:
        text = " ".join(
            str(item.get(field) or "")
            for field in ("title", "summary", "banner_image", "source")
        ).lower()
        if any(keyword in text for keyword in self.HIGH_IMPACT_KEYWORDS):
            return True
        score = self._sentiment_score(item)
        return score is not None and abs(score) >= 0.35

    @staticmethod
    def _source(item: dict[str, Any]) -> NewsSource:
        return NewsSource(
            title=str(item.get("title") or "Untitled news item"),
            url=item.get("url"),
            published_at=item.get("time_published"),
            sentiment_score=NewsRiskService._sentiment_score(item),
        )

    @staticmethod
    def _sentiment_score(item: dict[str, Any]) -> float | None:
        try:
            return float(item.get("overall_sentiment_score"))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _published_at(item: dict[str, Any]) -> datetime | None:
        raw = item.get("time_published")
        if not raw:
            return None
        try:
            return datetime.strptime(str(raw), "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
