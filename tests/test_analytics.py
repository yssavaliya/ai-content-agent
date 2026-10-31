from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import MagicMock, patch

from ai_content_agent.analytics.base import PostMetrics
from ai_content_agent.analytics.collector import AnalyticsCollector
from ai_content_agent.analytics.instagram import InstagramAnalyticsClient
from ai_content_agent.database.connection import DatabaseConnection


class InstagramAnalyticsClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = InstagramAnalyticsClient("token", "111", api_version="21.0")

    @patch("ai_content_agent.analytics.instagram.requests.get")
    def test_fetch_post_metrics_maps_values(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "data": [
                    {"name": "impressions", "period": "lifetime", "values": [{"value": 100}]},
                    {"name": "reach", "period": "lifetime", "values": [{"value": 80}]},
                    {"name": "engagement", "period": "lifetime", "values": [{"value": 5}]},
                ],
                "id": "media-1",
            },
        )
        metrics = self.client.fetch_post_metrics("media-1")

        self.assertEqual(metrics.media_id, "media-1")
        self.assertEqual(metrics.impressions, 100)
        self.assertEqual(metrics.reach, 80)
        self.assertIsNone(metrics.likes)
        self.assertEqual(metrics.engagement, 5)
        self.assertEqual(metrics.engagement_rate, 0.05)
        self.assertIn("data", metrics.raw)

    @patch("ai_content_agent.analytics.instagram.requests.get")
    def test_missing_metrics_are_never_zero(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": [], "id": "media-2"},
        )
        metrics = self.client.fetch_post_metrics("media-2")
        self.assertIsNone(metrics.impressions)
        self.assertIsNone(metrics.engagement_rate)

    @patch("ai_content_agent.analytics.instagram.requests.get")
    def test_raises_on_api_error(self, mock_get):
        mock_get.return_value = MagicMock(status_code=400, text="boom")
        with self.assertRaises(Exception):
            self.client.fetch_post_metrics("media-3")


class FakeProvider:
    @property
    def name(self) -> str:
        return "fake"

    def fetch_post_metrics(self, media_id: str) -> PostMetrics:
        return PostMetrics(
            media_id=media_id,
            impressions=100,
            reach=80,
            likes=10,
            comments=2,
            shares=1,
            saves=3,
            engagement=16,
            engagement_rate=0.16,
            collected_at="2026-08-06T00:00:00Z",
            raw={"data": []},
        )

    def fetch_account_insights(self, period_days: int = 30) -> dict:
        return {}


class FailingProvider(FakeProvider):
    def fetch_post_metrics(self, media_id: str) -> PostMetrics:
        raise RuntimeError("network down")


class AnalyticsCollectorTests(unittest.TestCase):
    def test_collect_persists_metrics_and_observations(self):
        db = DatabaseConnection(db_path=":memory:")
        try:
            db.execute(
                "INSERT INTO posts(external_id, caption, image_description, hashtags, created_at) VALUES (?, ?, ?, ?, ?)",
                ("media-1", "caption", "desc", "[]", "2026-08-01T00:00:00Z"),
            )
            post_id = db.execute("SELECT id FROM posts").fetchone()[0]

            collector = AnalyticsCollector(provider=FakeProvider(), database=db)
            summary = collector.collect()

            self.assertTrue(summary["enabled"])
            self.assertEqual(summary["collected"], 1)
            row = db.execute(
                "SELECT post_id, media_id, impressions, engagement_rate FROM post_metrics"
            ).fetchone()
            self.assertEqual(row[0], post_id)
            self.assertEqual(row[1], "media-1")
            self.assertEqual(row[2], 100)
            self.assertEqual(row[3], 0.16)

            observation = db.execute(
                "SELECT post_id, metric_name, metric_value FROM observations"
            ).fetchone()
            self.assertEqual(observation[0], post_id)
            self.assertEqual(observation[1], "engagement_rate")
            self.assertEqual(observation[2], 0.16)
        finally:
            db.close()

    def test_collect_continues_on_provider_failure(self):
        db = DatabaseConnection(db_path=":memory:")
        try:
            for index in range(2):
                db.execute(
                    "INSERT INTO posts(external_id, caption, image_description, hashtags, created_at) VALUES (?, ?, ?, ?, ?)",
                    (f"media-{index}", "caption", "desc", "[]", "2026-08-01T00:00:00Z"),
                )

            collector = AnalyticsCollector(provider=FailingProvider(), database=db)
            summary = collector.collect()

            self.assertEqual(summary["collected"], 0)
            self.assertEqual(summary["failed"], 2)
            self.assertEqual(len(summary["failures"]), 2)
        finally:
            db.close()

    def test_collect_only_refreshes_recent_posts_when_window_is_set(self):
        db = DatabaseConnection(db_path=":memory:")
        try:
            now = datetime.now(timezone.utc)
            for external_id, age_days in (("old", 90), ("recent", 3)):
                db.execute(
                    "INSERT INTO posts(external_id, caption, image_description, hashtags, created_at) VALUES (?, ?, ?, ?, ?)",
                    (external_id, "caption", "desc", "[]", (now - timedelta(days=age_days)).isoformat().replace("+00:00", "Z")),
                )

            windowed = AnalyticsCollector(provider=FakeProvider(), database=db, max_age_days=30).collect()
            self.assertEqual(windowed["posts_considered"], 1)
            self.assertEqual(db.execute("SELECT media_id FROM post_metrics").fetchone()[0], "recent")

            unlimited = AnalyticsCollector(provider=FakeProvider(), database=db).collect()
            self.assertEqual(unlimited["posts_considered"], 2)
        finally:
            db.close()

    def test_collect_without_provider_is_noop(self):
        db = DatabaseConnection(db_path=":memory:")
        try:
            collector = AnalyticsCollector(provider=None, database=db)
            summary = collector.collect()
            self.assertFalse(summary["enabled"])
            self.assertEqual(summary["collected"], 0)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
