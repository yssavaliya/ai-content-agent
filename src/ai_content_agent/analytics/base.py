from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PostMetrics:
    media_id: str
    impressions: int | None
    reach: int | None
    likes: int | None
    comments: int | None
    shares: int | None
    saves: int | None
    engagement: int | None
    engagement_rate: float | None
    collected_at: str
    raw: dict[str, Any] = field(default_factory=dict)


class AnalyticsProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def fetch_post_metrics(self, media_id: str) -> PostMetrics:
        raise NotImplementedError

    @abstractmethod
    def fetch_account_insights(self, period_days: int) -> dict[str, Any]:
        raise NotImplementedError
