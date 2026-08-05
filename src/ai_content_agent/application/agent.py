from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Sequence

from ..domain.models import ContentIdea, PostAnalytics, Trend
from ..domain.ports import AnalyticsCollector, ContentGenerator, SocialMediaPublisher, TrendSource


class ContentAgent:
    """Orchestrates one execution cycle of the autonomous content agent."""

    def __init__(
        self,
        trend_source: TrendSource,
        content_generator: ContentGenerator,
        publisher: SocialMediaPublisher,
        analytics_collector: AnalyticsCollector,
    ) -> None:
        self.trend_source = trend_source
        self.content_generator = content_generator
        self.publisher = publisher
        self.analytics_collector = analytics_collector

    def run_cycle(self, trend_limit: int = 3) -> dict[str, object]:
        """Run a single agent checkpoint cycle.

        The cycle is intentionally simple for this checkpoint:
        1. discover relevant trends
        2. generate an Instagram-ready content idea
        3. publish the content
        4. collect analytics for the published post

        This keeps the architecture clean and isolates domain interfaces from implementation.
        """
        trends = self.trend_source.discover_trends(limit=trend_limit)
        content = self.content_generator.generate_content(trends)
        post_id = self.publisher.publish_post(content)
        analytics = self.analytics_collector.collect(post_id=post_id)

        return {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "trends": [asdict(trend) for trend in trends],
            "content": asdict(content),
            "post_id": post_id,
            "analytics": asdict(analytics),
        }
