from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Iterable

from ..database.connection import DatabaseConnection
from .provider import ResearchProvider, ResearchTrend


logger = logging.getLogger(__name__)


class ResearchService:
    def __init__(self, providers: Iterable[ResearchProvider]) -> None:
        self.providers = list(providers)

    def collect(self) -> list[ResearchTrend]:
        trends: list[ResearchTrend] = []
        for provider in self.providers:
            try:
                provider_trends = provider.fetch_trends()
                trends.extend(provider_trends)
            except Exception:
                logger.exception("Research provider failed: %s", provider.name)
        return self._rank_trends(trends)

    def _rank_trends(self, trends: list[ResearchTrend]) -> list[ResearchTrend]:
        return sorted(trends, key=lambda trend: trend.title.lower())

    def persist_raw(self, trends: list[ResearchTrend], db: DatabaseConnection | None = None) -> list[int]:
        close_db = False
        if db is None:
            db = DatabaseConnection()
            close_db = True

        inserted_ids: list[int] = []
        try:
            for trend in trends:
                cursor = db.execute(
                    "INSERT INTO research_raw(provider, title, source, summary, category, url, retrieved_at, normalized_at, raw_payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        trend.provider,
                        trend.title,
                        trend.source,
                        trend.summary,
                        trend.category,
                        trend.url,
                        trend.retrieved_at,
                        datetime.utcnow().isoformat() + "Z",
                        json.dumps(trend.raw_payload),
                    ),
                )
                inserted_ids.append(cursor.lastrowid)
            return inserted_ids
        finally:
            if close_db and db is not None:
                db.close()
