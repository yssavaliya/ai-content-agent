import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from ai_content_agent.agents.research import ResearchAgent
from ai_content_agent.database.connection import DatabaseConnection
from ai_content_agent.opencode.client import OpenCodeClient, OpenCodeError
from ai_content_agent.prompts.manager import PromptManager


class ResearchAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.identity_path = Path("brain/identity.md")
        self.strategy_path = Path("brain/strategy.md")
        self.prompt_name = "research.md"

    def test_execute_returns_valid_research_output(self):
        client = MagicMock(spec=OpenCodeClient)
        client.run.return_value.stdout = json.dumps(
            {
                "recommended_topic": "Micro-content trends for creators",
                "audience_problem": "Creators struggle to convert engagement into meaningful growth.",
                "why_now": "Short-form video and carousel content are dominating discovery in 2026.",
                "hook": "Turn trend intelligence into reliable Instagram momentum.",
                "supporting_points": [
                    "Creators need content that balances inspiration with practical next steps.",
                    "Audience attention is more valuable than follower count right now.",
                    "Instagram formats reward repeatable narrative structures."
                ],
                "trend_signals": ["Reels carousels trending for Indian creators", "Festival season approaching"],
                "candidate_topics": ["Micro-content trends for creators", "Monetization tips for small creators"],
                "confidence": 92,
                "reasoning": "The brand is focused on research-driven content creation, so this topic aligns with strategy and audience needs.",
                "timestamp": "2026-08-05T00:00:00Z",
            }
        )

        db = DatabaseConnection(db_path=":memory:")
        try:
            agent = ResearchAgent(
                opencode_client=client,
                prompt_manager=PromptManager(prompt_dir=Path("src/ai_content_agent/prompts")),
                database=db,
            )
            result = agent.execute({
                "identity": str(self.identity_path),
                "strategy": str(self.strategy_path),
                "market": str(Path("brain/market.md")),
                "prompt": self.prompt_name,
            })
        finally:
            db.close()

        self.assertEqual(result["recommended_topic"], "Micro-content trends for creators")
        self.assertIsInstance(result["supporting_points"], list)
        self.assertEqual(result["confidence"], 92)
        self.assertIn("research_id", result)
        self.assertIsInstance(result["research_id"], int)

    def test_execute_raises_on_malformed_json(self):
        client = MagicMock(spec=OpenCodeClient)
        client.run.return_value.stdout = "{invalid json}"

        db = DatabaseConnection(db_path=":memory:")
        try:
            agent = ResearchAgent(
                opencode_client=client,
                prompt_manager=PromptManager(prompt_dir=Path("src/ai_content_agent/prompts")),
                database=db,
            )

            with self.assertRaises(RuntimeError):
                agent.execute({
                    "identity": str(self.identity_path),
                    "strategy": str(self.strategy_path),
                    "market": str(Path("brain/market.md")),
                    "prompt": self.prompt_name,
                })
        finally:
            db.close()

    def test_execute_retries_on_timeout(self):
        client = MagicMock(spec=OpenCodeClient)
        client.run.side_effect = [
            OpenCodeError("timeout", -1, "", ""),
            MagicMock(stdout=json.dumps(
                {
                    "recommended_topic": "Micro-content trends for creators",
                    "audience_problem": "Creators struggle to convert engagement into meaningful growth.",
                    "why_now": "Short-form video and carousel content are dominating discovery in 2026.",
                    "hook": "Turn trend intelligence into reliable Instagram momentum.",
                    "supporting_points": ["Point 1"],
                    "trend_signals": ["Signal A"],
                    "candidate_topics": ["Topic B"],
                    "confidence": 92,
                    "reasoning": "Reasoning.",
                    "timestamp": "2026-08-05T00:00:00Z",
                }
            )),
        ]

        db = DatabaseConnection(db_path=":memory:")
        try:
            agent = ResearchAgent(
                opencode_client=client,
                prompt_manager=PromptManager(prompt_dir=Path("src/ai_content_agent/prompts")),
                database=db,
            )
            result = agent.execute({
                "identity": str(self.identity_path),
                "strategy": str(self.strategy_path),
                "market": str(Path("brain/market.md")),
                "prompt": self.prompt_name,
            })
        finally:
            db.close()

        self.assertEqual(result["recommended_topic"], "Micro-content trends for creators")

    def test_execute_raises_on_schema_validation_failure(self):
        client = MagicMock(spec=OpenCodeClient)
        client.run.return_value.stdout = json.dumps(
            {
                "recommended_topic": "",
                "audience_problem": "",
                "why_now": "",
                "hook": "",
                "supporting_points": [],
                "confidence": "high",
                "reasoning": "",
                "timestamp": "",
            }
        )

        db = DatabaseConnection(db_path=":memory:")
        try:
            agent = ResearchAgent(
                opencode_client=client,
                prompt_manager=PromptManager(prompt_dir=Path("src/ai_content_agent/prompts")),
                database=db,
            )

            with self.assertRaises(RuntimeError):
                agent.execute({
                    "identity": str(self.identity_path),
                    "strategy": str(self.strategy_path),
                    "market": str(Path("brain/market.md")),
                    "prompt": self.prompt_name,
                })
        finally:
            db.close()

    def test_execute_renders_run_date_into_prompt(self):
        client = MagicMock(spec=OpenCodeClient)
        client.run.return_value.stdout = json.dumps(
            {
                "recommended_topic": "AI tools for Indian students",
                "audience_problem": "Students struggle to pick useful AI tools.",
                "why_now": "Exam season plus new AI releases.",
                "hook": "AI tools that actually save hours.",
                "supporting_points": ["Free tools first.", "Simple setup."],
                "trend_signals": ["New AI model launch"],
                "candidate_topics": ["AI study tools", "Anime exam break picks"],
                "confidence": 88,
                "reasoning": "Trend-aligned and useful today.",
                "timestamp": "2026-08-05T00:00:00Z",
            }
        )

        db = DatabaseConnection(db_path=":memory:")
        try:
            agent = ResearchAgent(
                opencode_client=client,
                prompt_manager=PromptManager(prompt_dir=Path("src/ai_content_agent/prompts")),
                database=db,
            )
            agent.execute({
                "identity": str(self.identity_path),
                "strategy": str(self.strategy_path),
                "market": str(Path("brain/market.md")),
                "prompt": self.prompt_name,
                "run_date": "2026-08-10",
            })
        finally:
            db.close()

        prompt_text = client.run.call_args.kwargs["input_text"]
        self.assertIn("2026-08-10", prompt_text)

    def test_execute_defaults_run_date_to_today(self):
        client = MagicMock(spec=OpenCodeClient)
        client.run.return_value.stdout = json.dumps(
            {
                "recommended_topic": "Anime recommendations for beginners",
                "audience_problem": "New fans do not know where to start.",
                "why_now": "Seasonal anime wave is starting.",
                "hook": "5 anime to start with this season.",
                "supporting_points": ["Short series first.", "Easy to binge."],
                "trend_signals": ["Season premiere weekend"],
                "candidate_topics": ["Beginner anime list", "AI anime art"],
                "confidence": 85,
                "reasoning": "High demand from new viewers.",
                "timestamp": "2026-08-05T00:00:00Z",
            }
        )

        db = DatabaseConnection(db_path=":memory:")
        try:
            agent = ResearchAgent(
                opencode_client=client,
                prompt_manager=PromptManager(prompt_dir=Path("src/ai_content_agent/prompts")),
                database=db,
            )
            agent.execute({
                "identity": str(self.identity_path),
                "strategy": str(self.strategy_path),
                "market": str(Path("brain/market.md")),
                "prompt": self.prompt_name,
            })
        finally:
            db.close()

        prompt_text = client.run.call_args.kwargs["input_text"]
        today = datetime.now(timezone.utc).date().isoformat()
        self.assertIn(today, prompt_text)


if __name__ == "__main__":
    unittest.main()
