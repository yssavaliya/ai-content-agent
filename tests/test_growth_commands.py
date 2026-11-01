import contextlib
import io
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from ai_content_agent.application.scheduler import (
    HOOK_CONTROL,
    HOOK_VARIANT,
    PLACEHOLDER_VARIANT,
    Scheduler,
)
from ai_content_agent.cli import main
from ai_content_agent.database.connection import DatabaseConnection, initialize_database
from ai_content_agent.growth.followers import FollowerCount, FollowerSourceError
from ai_content_agent.notifications.notifier import Notifier
from ai_content_agent.science.experiments import ExperimentRepository


class GrowthCommandTestCase(unittest.TestCase):
    extra_env: dict[str, str] = {}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "agent.db"
        initialize_database(self.db_path)
        self._cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self._env = patch.dict(
            os.environ,
            {
                "LOG_LEVEL": "WARNING",
                "DATABASE_PATH": str(self.db_path),
                "OPENCODE_COMMAND": "opencode",
                "INSTAGRAM_ENABLED": "false",
                "IMAGE_PROVIDER": "local",
                "NOTIFY_CHANNELS": "dryrun",
                **self.extra_env,
            },
            clear=True,
        )
        self._env.start()
        self.notifier = MagicMock(spec=Notifier)

    def tearDown(self):
        self._env.stop()
        os.chdir(self._cwd)
        self.tmp.cleanup()

    def rows(self, sql: str):
        connection = sqlite3.connect(self.db_path)
        try:
            return connection.execute(sql).fetchall()
        finally:
            connection.close()

    def cli(self, *args: str):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()


class SchedulerGrowthTests(GrowthCommandTestCase):
    def test_manual_follower_count_is_stored(self):
        result = Scheduler(notifier=self.notifier).run_followers(250)
        self.assertEqual(result, {"stage": "followers", "ok": True, "followers": 250, "source": "manual"})
        self.assertEqual(self.rows("SELECT followers, source FROM follower_snapshots"), [(250, "manual")])

    def test_without_a_source_it_explains_what_is_missing(self):
        result = Scheduler(notifier=self.notifier).run_followers()
        self.assertFalse(result["ok"])
        self.assertIn("INSTAGRAM_ACCESS_TOKEN", result["note"])
        self.assertEqual(self.rows("SELECT COUNT(*) FROM follower_snapshots"), [(0,)])


class InstagramFollowerSchedulerTests(GrowthCommandTestCase):
    extra_env = {"INSTAGRAM_ACCESS_TOKEN": "tok", "INSTAGRAM_ACCOUNT_ID": "111"}

    @patch("ai_content_agent.growth.followers.InstagramFollowerSource.fetch")
    def test_fetches_from_the_instagram_api(self, fetch):
        fetch.return_value = FollowerCount(412, 30, "instagram")
        Scheduler(notifier=self.notifier).run_followers()
        self.assertEqual(self.rows("SELECT followers, media_count, source FROM follower_snapshots"), [(412, 30, "instagram")])

    @patch("ai_content_agent.growth.followers.InstagramFollowerSource.fetch")
    def test_api_failure_alerts_and_propagates(self, fetch):
        fetch.side_effect = FollowerSourceError("token expired")
        with self.assertRaises(FollowerSourceError):
            Scheduler(notifier=self.notifier).run_followers()
        self.notifier.send_failure.assert_called_once()
        self.assertIn("token expired", self.notifier.send_failure.call_args.kwargs["body"])


class HealthAndDashboardTests(GrowthCommandTestCase):
    def test_health_alerts_when_something_needs_a_human(self):
        result = Scheduler(notifier=self.notifier).run_health()
        self.assertFalse(result["ok"])
        self.notifier.send_failure.assert_called_once()
        self.assertIn("No post has been recorded", self.notifier.send_failure.call_args.kwargs["body"])

    def test_dashboard_is_written_to_the_requested_path(self):
        result = Scheduler(notifier=self.notifier).run_dashboard("out/index.html")
        self.assertTrue(Path(result["path"]).exists())
        self.assertIn("Milestone progress", Path(result["path"]).read_text(encoding="utf-8"))

    def test_milestone_reports_the_first_target(self):
        Scheduler(notifier=self.notifier).run_followers(40)
        milestone = Scheduler(notifier=self.notifier).run_milestone()["milestone"]
        self.assertEqual((milestone.target, milestone.followers), (1000, 40))


class ExperimentUpgradeTests(GrowthCommandTestCase):
    def test_new_database_gets_a_concrete_hook_experiment(self):
        scheduler = Scheduler(notifier=self.notifier)
        db = DatabaseConnection()
        try:
            experiment_id = scheduler._ensure_experiment(db)
            experiment = ExperimentRepository(db).get(experiment_id)
        finally:
            db.close()
        self.assertEqual(experiment.variable, "hook-style")
        self.assertEqual(experiment.control_description, HOOK_CONTROL)
        self.assertEqual(experiment.variant_description, HOOK_VARIANT)
        self.assertNotEqual(HOOK_CONTROL, HOOK_VARIANT)

    def test_old_placeholder_experiment_is_upgraded_in_place(self):
        db = DatabaseConnection()
        try:
            old_id = ExperimentRepository(db).create(
                name="initial-content-strategy",
                description="old",
                variable="content-approach",
                control_description="Current default content approach",
                variant_description=PLACEHOLDER_VARIANT,
            )
            same_id = Scheduler(notifier=self.notifier)._ensure_experiment(db)
            experiment = ExperimentRepository(db).get(old_id)
        finally:
            db.close()
        self.assertEqual(same_id, old_id)
        self.assertEqual(experiment.variable, "hook-style")
        self.assertEqual(experiment.variant_description, HOOK_VARIANT)

    def test_customised_experiment_is_left_alone(self):
        db = DatabaseConnection()
        try:
            exp_id = ExperimentRepository(db).create(
                name="mine", description="d", variable="cta", control_description="A", variant_description="B"
            )
            Scheduler(notifier=self.notifier)._ensure_experiment(db)
            experiment = ExperimentRepository(db).get(exp_id)
        finally:
            db.close()
        self.assertEqual((experiment.variable, experiment.variant_description), ("cta", "B"))


class GrowthCliTests(GrowthCommandTestCase):
    def test_followers_records_a_manual_count(self):
        code, out, _ = self.cli("followers", "150")
        self.assertEqual(code, 0)
        self.assertIn("Recorded 150 followers", out)

    def test_followers_rejects_bad_numbers(self):
        for value in ("abc", "-5", "1.5"):
            with self.subTest(value=value):
                code, _, err = self.cli("followers", value)
                self.assertEqual(code, 2)
                self.assertTrue(err)

    def test_followers_without_source_exits_1_with_guidance(self):
        code, _, err = self.cli("followers")
        self.assertEqual(code, 1)
        self.assertIn("No follower source configured", err)

    def test_milestone_dashboard_and_health_commands(self):
        self.cli("followers", "120")
        code, out, _ = self.cli("milestone")
        self.assertEqual(code, 0)
        self.assertIn("Milestone: 1,000 followers", out)
        code, out, _ = self.cli("dashboard", "site/index.html")
        self.assertEqual(code, 0)
        self.assertTrue(Path("site/index.html").exists())
        code, out, _ = self.cli("health")
        self.assertEqual(code, 1)  # a fresh install has no posts yet
        self.assertIn("Needs attention", out)


if __name__ == "__main__":
    unittest.main()
