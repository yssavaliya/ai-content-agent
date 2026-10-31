from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any

from ..database.connection import DatabaseConnection
from ..timestamps import format_utc, utc_now, utc_now_iso
from .base import AnalyticsProvider, PostMetrics

logger = logging.getLogger(__name__)


class AnalyticsCollector:
    """Fetches Instagram insights for published posts and persists post_metrics."""

    def __init__(
        self,
        provider: AnalyticsProvider | None = None,
        database: DatabaseConnection | None = None,
        max_age_days: int | None = None,
    ) -> None:
        self.provider = provider
        self.database = database
        # Engagement stabilises within days; refreshing every post forever makes the number of API
        # calls per run grow without bound. None keeps the old behaviour (all posts).
        self.max_age_days = max_age_days

    def _get_database(self) -> DatabaseConnection:
        if self.database is None:
            self.database = DatabaseConnection()
        return self.database

    def _published_posts(self, db: DatabaseConnection) -> list[tuple[int, str]]:
        query = "SELECT id, external_id FROM posts WHERE external_id IS NOT NULL AND external_id != ''"
        parameters: tuple = ()
        if self.max_age_days is not None:
            query += " AND created_at >= ?"
            parameters = (format_utc(utc_now() - timedelta(days=self.max_age_days), "microseconds"),)
        with db.cursor() as cursor:
            cursor.execute(query, parameters)
            return [(int(row[0]), str(row[1])) for row in cursor.fetchall()]

    def _persist_metrics(self, db: DatabaseConnection, post_id: int, metrics: PostMetrics) -> int:
        cursor = db.execute(
            "INSERT INTO post_metrics(post_id, media_id, impressions, reach, likes, comments, shares, saves, engagement, engagement_rate, collected_at, raw_payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                post_id,
                metrics.media_id,
                metrics.impressions,
                metrics.reach,
                metrics.likes,
                metrics.comments,
                metrics.shares,
                metrics.saves,
                metrics.engagement,
                metrics.engagement_rate,
                metrics.collected_at,
                json.dumps(metrics.raw, default=str),
            ),
        )
        if metrics.engagement_rate is not None:
            db.execute(
                "INSERT INTO observations(collected_at, source, post_id, metric_name, metric_value, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    metrics.collected_at,
                    "instagram.insights",
                    post_id,
                    "engagement_rate",
                    metrics.engagement_rate,
                    json.dumps({"media_id": metrics.media_id}),
                ),
            )
        return cursor.lastrowid

    def collect(self) -> dict[str, Any]:
        owns_database = self.database is None
        db = self._get_database()
        try:
            if self.provider is None:
                logger.info("Analytics provider is not configured; skipping collection")
                return {"enabled": False, "collected": 0, "failed": 0, "failures": []}

            posts = self._published_posts(db)
            collected = 0
            failures: list[dict[str, Any]] = []
            for post_id, media_id in posts:
                try:
                    metrics = self.provider.fetch_post_metrics(media_id)
                    self._persist_metrics(db, post_id, metrics)
                    collected += 1
                except Exception as exc:
                    logger.warning("Analytics collection failed for post %s (%s): %s", post_id, media_id, exc)
                    failures.append({"post_id": post_id, "media_id": media_id, "error": str(exc)})

            summary: dict[str, Any] = {
                "enabled": True,
                "provider": self.provider.name,
                "posts_considered": len(posts),
                "collected": collected,
                "failed": len(failures),
                "failures": failures,
                "collected_at": utc_now_iso(),
            }
            logger.info(
                "Analytics collection complete: %s posts, %s failures",
                collected,
                len(failures),
            )
            return summary
        finally:
            if owns_database:
                db.close()
                self.database = None
