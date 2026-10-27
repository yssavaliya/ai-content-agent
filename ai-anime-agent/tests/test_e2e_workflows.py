from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from ai_content_agent.agents.creator import CreatorAgent
from ai_content_agent.agents.planner import PlannerAgent
from ai_content_agent.agents.predictor import PredictorAgent
from ai_content_agent.agents.research import ResearchAgent
from ai_content_agent.agents.reviewer import ReviewerAgent
from ai_content_agent.agents.scientist import ScientistAgent
from ai_content_agent.analytics.base import AnalyticsProvider, PostMetrics
from ai_content_agent.application.pipeline import ContentPipeline
from ai_content_agent.application.scheduler import Scheduler
from ai_content_agent.cli import main as cli_main
from ai_content_agent.database.connection import DatabaseConnection, initialize_database, run_migrations
from ai_content_agent.notifications.notifier import Notifier
from ai_content_agent.opencode.client import OpenCodeClient
from ai_content_agent.prompts.manager import PromptManager
from ai_content_agent.science.experiments import ExperimentRepository
from ai_content_agent.settings import load_settings
from ai_content_agent.timestamps import utc_now_iso

SAMPLE_RESEARCH_A = {
    "recommended_topic": "AI Automation Frameworks 2026",
    "audience_problem": "Engineers struggle to keep CI/CD pipelines deterministic under rapid AI agent evolution.",
    "why_now": "Agentic workflows require strict verification gates to ensure production readiness.",
    "hook": "Stop debugging broken pipelines in production.",
    "supporting_points": ["Deterministic test suites prevent CI regression loops."],
    "trend_signals": ["Autonomous QA tooling trending across tech teams"],
    "candidate_topics": ["AI Automation Frameworks 2026", "Zero-downtime Agentic Deployments"],
    "confidence": 95,
    "reasoning": "Directly addresses production validation needs in line with our engineering strategy.",
    "timestamp": "2026-10-27T00:00:00Z",
}

SAMPLE_PLANNER_A = {
    "ideas": [
        {
            "idea": "Deterministic CI/CD gates for agentic coding assistants",
            "educational_score": 0.9,
            "originality_score": 0.85,
            "engagement_score": 0.9,
            "relevance_score": 0.95,
            "reasoning": "High relevance to tech leads and QA specialists.",
        }
    ],
    "selected_idea": {
        "idea": "Deterministic CI/CD gates for agentic coding assistants",
        "educational_score": 0.9,
        "originality_score": 0.85,
        "engagement_score": 0.9,
        "relevance_score": 0.95,
        "total_score": 3.6,
        "reasoning": "Strongest score and directly actionable.",
    },
}

SAMPLE_CREATOR_A = {
    "carousel_outline": [
        "Slide 1: Why agentic workflows fail in CI",
        "Slide 2: The 5-stage verification pattern",
        "Slide 3: Implementation roadmap",
    ],
    "caption": "Deterministic CI/CD is the backbone of production-ready autonomous systems.",
    "cta": "Save this guide and review your workflow gates.",
    "hashtags": ["#devops", "#softwareengineering", "#productionready"],
    "image_prompt": "Futuristic clean visual representing continuous validation gates, high contrast, minimal design.",
    "alt_text": "Diagram showing automated verification stages in a modern continuous integration pipeline.",
}

SAMPLE_REVIEW_PASS = {
    "status": "PASS",
    "reasons": ["Meets technical standards.", "Zero brand policy violations.", "Clear CTA and alt text present."],
    "timestamp": "2026-10-27T00:00:00Z",
}

SAMPLE_REVIEW_FAIL = {
    "status": "FAIL",
    "reasons": ["Contains unverified claims.", "Tone violates brand guidelines."],
    "timestamp": "2026-10-27T00:00:00Z",
}

SAMPLE_PREDICTOR_A = {
    "virality_score": 88,
    "virality_label": "HIGH",
    "virality_probability": 0.82,
    "key_factors": ["High relevance", "Clear problem framing", "Engineering audience interest"],
    "risks": ["Niche audience"],
    "reasoning": "High engagement anticipated due to actionable DevOps guidance.",
    "timestamp": "2026-10-27T00:00:00Z",
}


class MockAnalyticsProvider(AnalyticsProvider):
    @property
    def name(self) -> str:
        return "mock"

    def fetch_post_metrics(self, media_id: str) -> PostMetrics:
        return PostMetrics(
            media_id=media_id,
            impressions=1500,
            reach=1200,
            likes=180,
            comments=24,
            shares=35,
            saves=50,
            engagement=289,
            engagement_rate=0.192,
            collected_at=utc_now_iso(),
            raw={"status": "ok"},
        )

    def fetch_account_insights(self, period_days: int) -> dict[str, Any]:
        return {"impressions": 10000, "reach": 8500}


class EndToEndWorkflowTests(unittest.TestCase):
    """End-to-end integration and workflow validation tests covering the complete application lifecycle."""

    def setUp(self) -> None:
        self._orig_cwd = os.getcwd()
        self._orig_env = dict(os.environ)
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.work_dir = Path(self.tmp_dir.name)

        # Mirror required project structure into isolated test sandbox
        repo_root = Path(__file__).resolve().parents[1]
        shutil.copytree(repo_root / "brain", self.work_dir / "brain")
        os.chdir(self.work_dir)

        self.db_path = self.work_dir / "agent.db"
        self.env_config = {
            "LOG_LEVEL": "INFO",
            "DATABASE_PATH": str(self.db_path),
            "OPENCODE_COMMAND": "opencode",
            "INSTAGRAM_ENABLED": "false",
            "IMAGE_PROVIDER": "local",
            "LLM_PROVIDER": "opencode",
            "INSTAGRAM_PUBLISH_ENABLED": "false",
            "INSTAGRAM_ANALYTICS_ENABLED": "false",
            "NOTIFY_CHANNELS": "dryrun",
        }
        os.environ.update(self.env_config)
        self.settings = load_settings(env=self.env_config)

    def tearDown(self) -> None:
        os.chdir(self._orig_cwd)
        os.environ.clear()
        os.environ.update(self._orig_env)
        self.tmp_dir.cleanup()

    def _mock_opencode(self, payload: dict) -> MagicMock:
        client = MagicMock(spec=OpenCodeClient)
        client.run.return_value.stdout = json.dumps(payload)
        return client

    def _wire_mocked_pipeline(
        self,
        pipeline: ContentPipeline,
        research_data: dict = SAMPLE_RESEARCH_A,
        planner_data: dict = SAMPLE_PLANNER_A,
        creator_data: dict = SAMPLE_CREATOR_A,
        review_data: dict = SAMPLE_REVIEW_PASS,
        predictor_data: dict = SAMPLE_PREDICTOR_A,
    ) -> None:
        pm = PromptManager()
        db = pipeline.database
        pipeline.research_agent = ResearchAgent(
            prompt_manager=pm,
            opencode_client=self._mock_opencode(research_data),
            database=db,
        )
        pipeline.planner_agent = PlannerAgent(
            prompt_manager=pm,
            opencode_client=self._mock_opencode(planner_data),
            database=db,
        )
        pipeline.creator_agent = CreatorAgent(
            prompt_manager=pm,
            opencode_client=self._mock_opencode(creator_data),
            database=db,
        )
        pipeline.reviewer_agent = ReviewerAgent(
            prompt_manager=pm,
            opencode_client=self._mock_opencode(review_data),
            database=db,
        )
        pipeline.predictor_agent = PredictorAgent(
            prompt_manager=pm,
            opencode_client=self._mock_opencode(predictor_data),
            database=db,
        )

    def test_clean_database_initialization_and_migrations(self) -> None:
        """Verify that a brand-new SQLite database initializes correctly and applies all migrations."""
        clean_db_file = self.work_dir / "clean_test.db"
        self.assertFalse(clean_db_file.exists())

        initialize_database(clean_db_file)
        self.assertTrue(clean_db_file.exists())

        run_migrations(clean_db_file)

        conn = sqlite3.connect(clean_db_file)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(version) FROM schema_migrations")
            version = cursor.fetchone()[0]
            self.assertEqual(version, 2)

            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}
            expected_tables = {
                "posts",
                "analytics",
                "experiments",
                "research_raw",
                "planner_ideas",
                "creator_outputs",
                "review_history",
                "image_assets",
                "publish_packages",
                "post_metrics",
                "observations",
                "experiment_posts",
                "strategy_history",
                "virality_predictions",
                "schema_migrations",
            }
            self.assertTrue(expected_tables.issubset(tables))
        finally:
            conn.close()

    def test_complete_daily_pipeline_real_user_workflow(self) -> None:
        """Execute the full content workflow: research -> plan -> create -> review -> predict -> image -> publish."""
        notifier = MagicMock(spec=Notifier)
        pipeline = ContentPipeline(settings=self.settings, notifier=notifier)
        self._wire_mocked_pipeline(pipeline)

        package = pipeline.run("run-e2e-001")

        # 1. Verify in-memory package structure
        self.assertEqual(package["run_id"], "run-e2e-001")
        self.assertEqual(package["research"]["recommended_topic"], SAMPLE_RESEARCH_A["recommended_topic"])
        self.assertEqual(package["planning"]["selected_idea"]["idea"], SAMPLE_PLANNER_A["selected_idea"]["idea"])
        self.assertEqual(package["creation"]["caption"], SAMPLE_CREATOR_A["caption"])
        self.assertEqual(package["review"]["status"], "PASS")
        self.assertEqual(package["prediction"]["virality_score"], 88)
        self.assertEqual(package["image"]["provider"], "local")
        self.assertEqual(package["publish"]["status"], "dry-run")

        # 2. Verify file outputs on disk
        pkg_file = Path(package["package_path"])
        self.assertTrue(pkg_file.exists(), "publish_package JSON file must exist on disk")
        pkg_disk = json.loads(pkg_file.read_text(encoding="utf-8"))
        self.assertEqual(pkg_disk["run_id"], "run-e2e-001")

        kit_path = Path(package["publish"]["metadata"]["kit_path"])
        self.assertTrue(kit_path.exists(), "post_kit Markdown file must exist on disk")
        kit_content = kit_path.read_text(encoding="utf-8")
        self.assertIn(SAMPLE_CREATOR_A["caption"], kit_content)
        self.assertIn("#devops", kit_content)
        self.assertIn(SAMPLE_CREATOR_A["alt_text"], kit_content)
        self.assertIn(SAMPLE_CREATOR_A["carousel_outline"][0], kit_content)

        img_file = Path(package["image"]["file_path"])
        self.assertTrue(img_file.exists(), "Image asset file must exist on disk")

        # 3. Verify SQLite persistence and relational integrity via direct queries
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.cursor()

            # research_raw
            cur.execute("SELECT id, title, source, summary FROM research_raw")
            r_rows = cur.fetchall()
            self.assertEqual(len(r_rows), 1)
            research_id = r_rows[0][0]
            self.assertEqual(r_rows[0][1], SAMPLE_RESEARCH_A["recommended_topic"])

            # planner_ideas
            cur.execute("SELECT id, research_id, idea_text, total_score, selected FROM planner_ideas")
            p_rows = cur.fetchall()
            self.assertEqual(len(p_rows), 1)
            planner_id = p_rows[0][0]
            self.assertEqual(p_rows[0][1], research_id, "planner_ideas.research_id must link to research_raw.id")
            self.assertEqual(p_rows[0][4], 1)

            # creator_outputs
            cur.execute("SELECT id, planner_id, caption, alt_text FROM creator_outputs")
            c_rows = cur.fetchall()
            self.assertEqual(len(c_rows), 1)
            creator_output_id = c_rows[0][0]
            self.assertEqual(c_rows[0][1], planner_id, "creator_outputs.planner_id must link to planner_ideas.id")
            self.assertEqual(c_rows[0][2], SAMPLE_CREATOR_A["caption"])

            # review_history
            cur.execute("SELECT creator_output_id, status FROM review_history")
            rev_rows = cur.fetchall()
            self.assertEqual(len(rev_rows), 1)
            self.assertEqual(rev_rows[0][0], creator_output_id)
            self.assertEqual(rev_rows[0][1], "PASS")

            # virality_predictions
            cur.execute("SELECT creator_output_id, virality_score, virality_label FROM virality_predictions")
            pred_rows = cur.fetchall()
            self.assertEqual(len(pred_rows), 1)
            self.assertEqual(pred_rows[0][0], creator_output_id)
            self.assertEqual(pred_rows[0][1], 88)
            self.assertEqual(pred_rows[0][2], "HIGH")

            # image_assets
            cur.execute("SELECT creator_output_id, provider, file_path FROM image_assets")
            img_rows = cur.fetchall()
            self.assertEqual(len(img_rows), 1)
            self.assertEqual(img_rows[0][0], creator_output_id)
            self.assertEqual(img_rows[0][1], "local")

            # publish_packages
            cur.execute("SELECT creator_output_id, status, package_path FROM publish_packages")
            pub_rows = cur.fetchall()
            self.assertEqual(len(pub_rows), 1)
            self.assertEqual(pub_rows[0][0], creator_output_id)
            self.assertEqual(pub_rows[0][1], "dry-run")
        finally:
            conn.close()

        # 4. Verify notification call
        notifier.send_success.assert_called_once()
        self.assertIn("ready for manual publishing", notifier.send_success.call_args.kwargs["subject"])

    def test_persistence_across_multiple_runs(self) -> None:
        """Confirm that multiple runs coexist cleanly in the database without overwriting or corruption."""
        for run_idx in (1, 2):
            run_id = f"run-multi-{run_idx}"
            research_data = dict(SAMPLE_RESEARCH_A, recommended_topic=f"Topic Sequence {run_idx}")
            pipeline = ContentPipeline(settings=self.settings)
            self._wire_mocked_pipeline(pipeline, research_data=research_data)
            pipeline.run(run_id)

        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM research_raw")
            self.assertEqual(cur.fetchone()[0], 2)
            cur.execute("SELECT COUNT(*) FROM creator_outputs")
            self.assertEqual(cur.fetchone()[0], 2)
            cur.execute("SELECT COUNT(*) FROM publish_packages")
            self.assertEqual(cur.fetchone()[0], 2)

            cur.execute("SELECT title FROM research_raw ORDER BY id")
            topics = [row[0] for row in cur.fetchall()]
            self.assertEqual(topics, ["Topic Sequence 1", "Topic Sequence 2"])
        finally:
            conn.close()

    def test_review_failure_safely_blocks_image_and_publishing(self) -> None:
        """Verify that when the ReviewerAgent returns FAIL, no image is generated and publish is blocked."""
        notifier = MagicMock(spec=Notifier)
        pipeline = ContentPipeline(settings=self.settings, notifier=notifier)
        self._wire_mocked_pipeline(pipeline, review_data=SAMPLE_REVIEW_FAIL)

        package = pipeline.run("run-blocked-001")

        self.assertEqual(package["publish"]["status"], "blocked_review")
        self.assertIsNone(package["image"])
        self.assertIsNone(package["prediction"])

        # Check DB state
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM image_assets")
            self.assertEqual(cur.fetchone()[0], 0, "No image asset must be persisted when review fails")

            cur.execute("SELECT status FROM publish_packages")
            pub_status = cur.fetchone()[0]
            self.assertEqual(pub_status, "blocked_review")
        finally:
            conn.close()

        # Check notification
        notifier.send_failure.assert_called_once()
        self.assertIn("post blocked by review", notifier.send_failure.call_args.kwargs["subject"])
        self.assertIn("Contains unverified claims", notifier.send_failure.call_args.kwargs["body"])

    def test_analytics_and_scientist_learning_loop_workflow(self) -> None:
        """Verify the full analytics collection and Scientist experiment learning loop."""
        scheduler = Scheduler(settings=self.settings, strategy_path="brain/strategy.md")

        # 1. Run analytics (disabled in settings, should complete cleanly)
        analytics_result = scheduler.run_analytics()
        self.assertTrue(analytics_result["ok"])
        self.assertFalse(analytics_result["summary"]["enabled"])

        # 2. Seed an experiment with arms and metrics to test scientist
        db = DatabaseConnection()
        try:
            repo = ExperimentRepository(db)
            exp_id = repo.create(
                name="headline-hook-experiment",
                description="Testing short punchy hooks vs narrative hooks",
                variable="hook-format",
                min_effect=0.15,
                confidence_threshold=0.6,
            )

            # Insert control and variant posts with simulated metrics
            for i in range(12):
                # control post
                cur = db.execute(
                    "INSERT INTO posts(external_id, caption, image_description, hashtags, created_at) "
                    "VALUES (?, 'control caption', 'desc', '[]', '2026-10-27T00:00:00Z')",
                    (f"post-ctrl-{i}",),
                )
                ctrl_id = cur.lastrowid
                repo.assign_post(exp_id, ctrl_id, "control")
                db.execute(
                    "INSERT INTO post_metrics(post_id, media_id, impressions, reach, likes, comments, shares, saves, engagement, engagement_rate, collected_at, raw_payload) "
                    "VALUES (?, ?, 1000, 800, 50, 5, 2, 5, 62, 0.062, '2026-10-27T00:00:00Z', '{}')",
                    (ctrl_id, f"media-ctrl-{i}"),
                )

                # variant post (substantially higher engagement to produce significant effect)
                cur = db.execute(
                    "INSERT INTO posts(external_id, caption, image_description, hashtags, created_at) "
                    "VALUES (?, 'variant caption', 'desc', '[]', '2026-10-27T00:00:00Z')",
                    (f"post-var-{i}",),
                )
                var_id = cur.lastrowid
                repo.assign_post(exp_id, var_id, "variant")
                db.execute(
                    "INSERT INTO post_metrics(post_id, media_id, impressions, reach, likes, comments, shares, saves, engagement, engagement_rate, collected_at, raw_payload) "
                    "VALUES (?, ?, 1000, 800, 150, 20, 15, 25, 210, 0.210, '2026-10-27T00:00:00Z', '{}')",
                    (var_id, f"media-var-{i}"),
                )
        finally:
            db.close()

        # 3. Run scientist analysis with mock agent recommendation
        fake_scientist = MagicMock(spec=ScientistAgent)
        fake_scientist.execute.return_value = {
            "summary": "Variant hook format shows significant lift in engagement rate.",
            "recommendations": [
                {
                    "strategy_guideline": "Always use punchy direct hooks under 10 words for engineering content.",
                    "rationale": "Variant arm produced Cohen's d > 0.5 with p < 0.01 across 24 posts.",
                    "variable": "hook-format",
                    "observed_effect": 0.65,
                    "sample_size": 24,
                    "confidence": 0.95,
                    "significance_p": 0.005,
                }
            ],
        }

        with patch("ai_content_agent.application.scheduler.ScientistAgent", return_value=fake_scientist):
            scientist_result = scheduler.run_scientist()

        self.assertTrue(scientist_result["ok"])
        self.assertEqual(scientist_result["applied_count"], 1)

        # 4. Confirm strategy.md was updated on disk with the evidence-backed guideline
        strategy_text = Path("brain/strategy.md").read_text(encoding="utf-8")
        self.assertIn("Always use punchy direct hooks under 10 words for engineering content.", strategy_text)
        self.assertIn("Evidence-backed guidance", strategy_text)

        # 5. Confirm strategy_history row was added to database
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.cursor()
            cur.execute("SELECT trigger, new_text FROM strategy_history")
            sh_rows = cur.fetchall()
            self.assertEqual(len(sh_rows), 1)
            self.assertEqual(sh_rows[0][0], "scientist")
        finally:
            conn.close()

    def test_monthly_report_workflow(self) -> None:
        """Verify monthly digest aggregation queries and reporting."""
        scheduler = Scheduler(settings=self.settings)
        result = scheduler.run_monthly()
        self.assertTrue(result["ok"])
        digest = result["digest"]
        self.assertIn("published_posts", digest)
        self.assertIn("experiments_completed", digest)
        self.assertIn("strategy_changes", digest)
        self.assertIn("observations", digest)

    def test_cli_interface_workflows(self) -> None:
        """Verify CLI behaviors: help, invalid commands, and missing configuration."""
        # 1. Help flag exits 0
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli_main(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("Usage: ai-content-agent", out.getvalue())

        # 2. Unknown command exits 2
        err = io.StringIO()
        with redirect_stderr(err):
            code = cli_main(["invalid_command_xyz"])
        self.assertEqual(code, 2)
        self.assertIn("Unknown command: invalid_command_xyz", err.getvalue())

        # 3. Missing config exits 1 cleanly without uncaught exception
        with patch.dict(os.environ, {}, clear=True):
            err = io.StringIO()
            with redirect_stderr(err):
                code = cli_main(["daily"])
            self.assertEqual(code, 1)
            self.assertIn("Missing required configuration values", err.getvalue())
            self.assertNotIn("Traceback", err.getvalue())


if __name__ == "__main__":
    unittest.main()
