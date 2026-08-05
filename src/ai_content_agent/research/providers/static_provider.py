from __future__ import annotations

from datetime import datetime
from typing import Any

from ..provider import ResearchProvider, ResearchTrend


class StaticResearchProvider(ResearchProvider):
    @property
    def name(self) -> str:
        return "static"

    def fetch_trends(self) -> list[ResearchTrend]:
        now = datetime.utcnow().isoformat() + "Z"
        return [
            ResearchTrend(
                provider=self.name,
                title="AI content personalization for creators",
                source="industry-report",
                summary="Creators are increasingly using personalized AI-driven content strategies to boost engagement.",
                category="content",
                url="https://example.com/ai-content-personalization",
                retrieved_at=now,
                raw_payload={"note": "static sample"},
            ),
            ResearchTrend(
                provider=self.name,
                title="Short-form video trends in 2026",
                source="social-insights",
                summary="Short-form videos remain the dominant format for discovery and audience growth.",
                category="video",
                url="https://example.com/short-form-video-2026",
                retrieved_at=now,
                raw_payload={"note": "static sample"},
            ),
        ]
