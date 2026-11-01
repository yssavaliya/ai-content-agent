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

    def has_data(self) -> bool:
        """False when the provider returned no numbers at all (e.g. a post too new to have insights)."""
        return any(
            value is not None
            for value in (
                self.impressions,
                self.reach,
                self.likes,
                self.comments,
                self.shares,
                self.saves,
                self.engagement,
            )
        )


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
