import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from ai_content_agent.agents.creator import CreatorAgent
from ai_content_agent.agents.planner import PlannerAgent
from ai_content_agent.agents.research import ResearchAgent
from ai_content_agent.agents.reviewer import ReviewerAgent
from ai_content_agent.application.pipeline import ContentPipeline
from ai_content_agent.opencode.client import OpenCodeClient
from ai_content_agent.prompts.manager import PromptManager

RESEARCH_OUTPUT = {
    "recommended_topic": "Micro-content trends for creators",
    "audience_problem": "Creators struggle to convert engagement into meaningful growth.",
    "why_now": "Short-form video and carousel content are dominating discovery in 2026.",
    "hook": "Turn trend intelligence into reliable Instagram momentum.",
    "supporting_points": ["Creators need content that balances inspiration with practical next steps."],
    "confidence": 92,
    "reasoning": "The brand is focused on research-driven content creation, so this topic aligns with strategy and audience needs.",
    "timestamp": "2026-08-05T00:00:00Z",
}

PLANNER_OUTPUT = {
    "ideas": [
        {
            "idea": "Turn trend intelligence into a repeatable carousel series",
            "educational_score": 0.8,
            "originality_score": 0.7,
            "engagement_score": 0.9,
            "relevance_score": 0.9,
            "reasoning": "Directly extends the research topic.",
        }
    ],
    "selected_idea": {
        "idea": "Turn trend intelligence into a repeatable carousel series",
        "educational_score": 0.8,
        "originality_score": 0.7,
        "engagement_score": 0.9,
        "relevance_score": 0.9,
        "total_score": 3.3,
        "reasoning": "Highest combined score and most aligned with the research recommendation.",
    },
}

CREATOR_OUTPUT = {
    "carousel_outline": [
        "Slide 1: Open with the audience problem.",
        "Slide 2: Share a practical framework.",
    ],
    "caption": "Trend intelligence only works when you turn it into a repeatable system.",
    "cta": "Save this post and follow for more.",
    "hashtags": ["#contentstrategy", "#creatoreconomy"],
    "image_prompt": "A clean carousel cover image with bold typography.",
    "alt_text": "A minimalist carousel cover with bold typography on a light gradient.",
}

REVIEWER_OUTPUT = {
    "status": "PASS",
    "reasons": ["Grammar is correct.", "Tone matches the brand voice.", "All slides are present."],
    "timestamp": "2026-08-05T00:00:00Z",
}


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_env = dict(os.environ)
        self._temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._temp_dir.name) / "pipeline.db"
        os.environ.update(
            {
                "LOG_LEVEL": "DEBUG",
                "DATABASE_PATH": str(self.db_path),
                "OPENCODE_COMMAND": "opencode",
                "INSTAGRAM_ENABLED": "false",
                "IMAGE_PROVIDER": "local",
            }
        )

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._original_env)
        self._temp_dir.cleanup()

    def _mocked_client(self, output: dict) -> MagicMock:
        client = MagicMock(spec=OpenCodeClient)
        client.run.return_value.stdout = json.dumps(output)
        return client

    def _build_pipeline(self) -> ContentPipeline:
        pipeline = ContentPipeline()
        prompt_manager = PromptManager(prompt_dir=Path("src/ai_content_agent/prompts"))
        database = pipeline.database
        pipeline.research_agent = ResearchAgent(
            prompt_manager=prompt_manager,
            opencode_client=self._mocked_client(RESEARCH_OUTPUT),
            database=database,
        )
        pipeline.planner_agent = PlannerAgent(
            prompt_manager=prompt_manager,
            opencode_client=self._mocked_client(PLANNER_OUTPUT),
            database=database,
        )
        pipeline.creator_agent = CreatorAgent(
            prompt_manager=prompt_manager,
            opencode_client=self._mocked_client(CREATOR_OUTPUT),
            database=database,
        )
        pipeline.reviewer_agent = ReviewerAgent(
            prompt_manager=prompt_manager,
            opencode_client=self._mocked_client(REVIEWER_OUTPUT),
            database=database,
        )
        return pipeline

    def test_run_pipeline_generates_package(self):
        pipeline = self._build_pipeline()
        result = pipeline.run()

        self.assertIn("research", result)
        self.assertIn("planning", result)
        self.assertIn("creation", result)
        self.assertIn("review", result)
        self.assertIn("image", result)
        self.assertIn("publish", result)
        self.assertTrue(Path("posts").exists())
        self.assertTrue(Path(result["image"]["file_path"]).exists())

    def test_run_pipeline_links_research_id(self):
        pipeline = self._build_pipeline()
        result = pipeline.run()

        self.assertIn("research_id", result["research"])
        research_id = result["research"]["research_id"]
        self.assertIsInstance(research_id, int)

        connection = sqlite3.connect(self.db_path)
        try:
            planner_row = connection.execute(
                "SELECT research_id, idea_text, educational_score, originality_score, engagement_score, relevance_score, total_score, reasoning FROM planner_ideas"
            ).fetchone()
            self.assertIsNotNone(planner_row)
            self.assertEqual(planner_row[0], research_id)
            self.assertEqual(planner_row[1], PLANNER_OUTPUT["selected_idea"]["idea"])
            self.assertEqual(planner_row[2], 0.8)
            self.assertEqual(planner_row[3], 0.7)
            self.assertEqual(planner_row[4], 0.9)
            self.assertEqual(planner_row[5], 0.9)
            self.assertEqual(planner_row[6], 3.3)
            self.assertEqual(planner_row[7], PLANNER_OUTPUT["selected_idea"]["reasoning"])

            creator_row = connection.execute(
                "SELECT planner_id, caption, alt_text FROM creator_outputs"
            ).fetchone()
            self.assertIsNotNone(creator_row)
            self.assertEqual(creator_row[1], CREATOR_OUTPUT["caption"])
            self.assertEqual(creator_row[2], CREATOR_OUTPUT["alt_text"])

            review_row = connection.execute(
                "SELECT creator_output_id, status, feedback, timestamp FROM review_history"
            ).fetchone()
            self.assertIsNotNone(review_row)
            self.assertEqual(review_row[1], REVIEWER_OUTPUT["status"])
            self.assertEqual(json.loads(review_row[2]), REVIEWER_OUTPUT["reasons"])
            self.assertTrue(review_row[3])

            image_row = connection.execute(
                "SELECT creator_output_id, provider, prompt, file_path FROM image_assets"
            ).fetchone()
            self.assertIsNotNone(image_row)
            self.assertEqual(image_row[1], "local")

            publish_row = connection.execute(
                "SELECT creator_output_id, status, package_path FROM publish_packages"
            ).fetchone()
            self.assertIsNotNone(publish_row)
            self.assertEqual(publish_row[1], "dry-run")
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
