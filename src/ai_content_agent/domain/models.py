from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence


@dataclass(frozen=True)
class Trend:
    topic: str
    relevance_score: float
    discovered_at: datetime


@dataclass(frozen=True)
class ContentIdea:
    caption: str
    image_description: str
    hashtags: Sequence[str]


@dataclass(frozen=True)
class PostAnalytics:
    post_id: str
    impressions: int
    engagements: int
    timestamp: datetime
