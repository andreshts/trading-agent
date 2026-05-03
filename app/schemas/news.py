from typing import Literal

from pydantic import BaseModel, Field


NewsRiskLevel = Literal["UNKNOWN", "LOW", "MEDIUM", "HIGH", "BLOCK"]
NewsRiskAction = Literal["allow", "block_new_entries"]


class NewsSource(BaseModel):
    title: str
    url: str | None = None
    published_at: str | None = None
    sentiment_score: float | None = None


class NewsRiskDecision(BaseModel):
    enabled: bool = True
    risk_level: NewsRiskLevel = "UNKNOWN"
    action: NewsRiskAction = "allow"
    summary: str = "News risk gate unavailable or no high-impact news found."
    confidence: float = Field(default=0, ge=0, le=1)
    sources: list[NewsSource] = Field(default_factory=list)
