from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ResearchTrend:
    provider: str
    title: str
    source: str
    summary: str
    category: str
    url: str | None
    retrieved_at: str
    raw_payload: dict[str, Any]


class ResearchProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def fetch_trends(self) -> list[ResearchTrend]:
        raise NotImplementedError
