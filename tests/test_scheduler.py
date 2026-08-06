import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from ai_content_agent.application.scheduler import Scheduler
from ai_content_agent.database.connection import DatabaseConnection
from ai_content_agent.science.experiments import ExperimentRepository
from tests.helpers import base_env


class SchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_env = dict(os.environ)
        self._temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._temp_dir.name) / "scheduler.db"
        os.environ.update(base_env(DATABASE_PATH=str(self.db_path)))
        self.notifier = MagicMock()

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._original_env)
        self._temp_dir.cleanup()

    def test_run_daily(self):
        package = {"run_id": "abc123"}
        pipeline = MagicMock()
        pipeline.run.return_value = package
        with patch("ai_content_agent.application.scheduler.ContentPipeline", return_value=pipeline):
            result = Scheduler(notifier=self.notifier).run_daily()

        self.assertTrue(result["ok"])
        self.assertEqual(result["stage"], "daily")
        self.assertEqual(result["run_id"], "abc123")
        pipeline.close.assert_called_once()

    def test_run_analytics_when_disabled(self):
        with patch(
            "ai_content_agent.application.scheduler.AnalyticsRegistry.build_provider",
            return_value=None,
        ):
            result = Scheduler(notifier=self.notifier).run_analytics()

        self.assertTrue(result["ok"])
        self.assertFalse(result["summary"]["enabled"])
        self.notifier.send_success.assert_not_called()

    def test_run_scientist_waits_for_data(self):
        scheduler = Scheduler(notifier=self.notifier)
        result = scheduler.run_scientist()

        self.assertTrue(result["ok"])
        self.assertIn("experiment_id", result)
        self.assertIn("no posts with analytics yet", result["note"])

        db = DatabaseConnection(db_path=self.db_path)
        try:
            self.assertEqual(len(ExperimentRepository(db).list_active()), 1)
        finally:
            db.close()

    def test_run_scientist_with_data_and_no_recommendations(self):
        db = DatabaseConnection(db_path=self.db_path)
        try:
            repository = ExperimentRepository(db)
            experiment_id = repository.create(name="exp", description="exp", variable="approach")
            for index in range(2):
                cursor = db.execute(
                    "INSERT INTO posts(external_id, caption, image_description, hashtags, created_at) VALUES (?, ?, ?, ?, ?)",
                    (f"media-{index}", "c", "d", "[]", "2026-08-01T00:00:00Z"),
                )
                post_id = cursor.lastrowid
                repository.assign_post(experiment_id, post_id, "control" if index % 2 == 0 else "variant")
                db.execute(
                    "INSERT INTO post_metrics(post_id, media_id, engagement_rate, collected_at, raw_payload) VALUES (?, ?, ?, ?, ?)",
                    (post_id, f"media-{index}", 0.05, "2026-08-06T00:00:00Z", "{}"),
                )
        finally:
            db.close()

        fake_scientist = MagicMock()
        fake_scientist.execute.return_value = {
            "recommendations": [],
            "summary": "No evidence cleared the bar.",
        }
        with patch("ai_content_agent.application.scheduler.ScientistAgent", return_value=fake_scientist):
            result = Scheduler(notifier=self.notifier).run_scientist()

        self.assertTrue(result["ok"])
        self.assertEqual(result["applied_count"], 0)
        self.assertEqual(result["summary"], "No evidence cleared the bar.")
        self.notifier.send_success.assert_called_once()

    def test_run_monthly(self):
        result = Scheduler(notifier=self.notifier).run_monthly()

        self.assertTrue(result["ok"])
        digest = result["digest"]
        self.assertEqual(digest["published_posts"], 0)
        self.assertIn("strategy_changes", digest)
        self.notifier.send_success.assert_called_once()


if __name__ == "__main__":
    unittest.main()
