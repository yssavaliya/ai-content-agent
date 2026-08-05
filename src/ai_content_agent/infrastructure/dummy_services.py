from __future__ import annotations

import random
from datetime import datetime
from typing import Sequence

from ..domain.models import ContentIdea, PostAnalytics, Trend
from ..domain.ports import AnalyticsCollector, ContentGenerator, SocialMediaPublisher, TrendSource


class DummyTrendSource(TrendSource):
    """Stub trend discovery for Phase X / Checkpoint Y.

    TODO: Replace with real trend research service in a later phase.
    """

    def discover_trends(self, limit: int = 3) -> Sequence[Trend]:
        topics = [
            "micro-influencer tips",
            "reel editing hacks",
            "AI lifestyle content",
            "eco-friendly branding",
            "creator monetization",
        ]
        return [
            Trend(topic=topics[i], relevance_score=round(1.0 - i * 0.15, 2), discovered_at=datetime.utcnow())
            for i in range(min(limit, len(topics)))
        ]


class DummyContentGenerator(ContentGenerator):
    """Stub content generator for Phase X / Checkpoint Y.

    TODO: Replace with a real content generation engine in a later phase.
    """

    def generate_content(self, trends: Sequence[Trend]) -> ContentIdea:
        trending_phrases = ", ".join(trend.topic for trend in trends)
        return ContentIdea(
            caption=(
                f"Top trends right now: {trending_phrases}."
                " Create engaging Instagram content with these ideas!"
            ),
            image_description=(
                "A polished Instagram carousel mockup showcasing the latest social media trends, "
                "with bold typography and a clean visual style."
            ),
            hashtags=["#contentstrategy", "#socialmedia", "#creatoreconomy"],
        )


class DummySocialMediaPublisher(SocialMediaPublisher):
    """Stub publisher for Phase X / Checkpoint Y.

    TODO: Replace with real Instagram API integration when ready.
    """

    def publish_post(self, content: ContentIdea) -> str:
        post_id = f"demo-post-{int(datetime.utcnow().timestamp())}"
        print(f"[Publisher] Simulated publish for post_id={post_id}")
        print(f"[Publisher] Caption: {content.caption}")
        return post_id


class DummyAnalyticsCollector(AnalyticsCollector):
    """Stub analytics collector for Phase X / Checkpoint Y.

    TODO: Replace with real analytics ingestion service in a later phase.
    """

    def collect(self, post_id: str) -> PostAnalytics:
        return PostAnalytics(
            post_id=post_id,
            impressions=random.randint(100, 1000),
            engagements=random.randint(10, 200),
            timestamp=datetime.utcnow(),
        )
