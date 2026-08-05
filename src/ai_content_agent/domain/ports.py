from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from .models import ContentIdea, PostAnalytics, Trend


class TrendSource(ABC):
    @abstractmethod
    def discover_trends(self, limit: int = 3) -> Sequence[Trend]:
        raise NotImplementedError


class ContentGenerator(ABC):
    @abstractmethod
    def generate_content(self, trends: Sequence[Trend]) -> ContentIdea:
        raise NotImplementedError


class SocialMediaPublisher(ABC):
    @abstractmethod
    def publish_post(self, content: ContentIdea) -> str:
        raise NotImplementedError


class AnalyticsCollector(ABC):
    @abstractmethod
    def collect(self, post_id: str) -> PostAnalytics:
        raise NotImplementedError
