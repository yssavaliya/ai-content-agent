from __future__ import annotations

import sys
from typing import Sequence

from .application.agent import ContentAgent
from .infrastructure import (
    DummyAnalyticsCollector,
    DummyContentGenerator,
    DummySocialMediaPublisher,
    DummyTrendSource,
)


def _print_results(results: dict[str, object]) -> None:
    print("AI Content Agent checkpoint run completed.")
    print(f"Timestamp: {results['timestamp']}")
    print("Discovered trends:")
    for trend in results["trends"]:
        print(f" - {trend['topic']} (score: {trend['relevance_score']})")
    print("Generated content idea:")
    print(f" - Caption: {results['content']['caption']}")
    print(f" - Image description: {results['content']['image_description']}")
    print(f" - Hashtags: {', '.join(results['content']['hashtags'])}")
    print(f"Published post id: {results['post_id']}")
    print("Collected analytics:")
    print(f" - Impressions: {results['analytics']['impressions']}")
    print(f" - Engagements: {results['analytics']['engagements']}")


def main(argv: Sequence[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    trend_limit = 3
    if argv:
        try:
            trend_limit = int(argv[0])
        except ValueError:
            print("Usage: ai-content-agent [trend_limit]")
            return 1

    agent = ContentAgent(
        trend_source=DummyTrendSource(),
        content_generator=DummyContentGenerator(),
        publisher=DummySocialMediaPublisher(),
        analytics_collector=DummyAnalyticsCollector(),
    )

    results = agent.run_cycle(trend_limit=trend_limit)
    _print_results(results)
    return 0
