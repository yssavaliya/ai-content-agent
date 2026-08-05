import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from ai_content_agent.agents.creator import CreatorAgent
from ai_content_agent.agents.planner import PlannerAgent
from ai_content_agent.agents.research import ResearchAgent
from ai_content_agent.agents.reviewer import ReviewerAgent
from ai_content_agent.database.connection import DatabaseConnection
from ai_content_agent.opencode.client import OpenCodeClient
from ai_content_agent.prompts.manager import PromptManager


class AgentFrameworkTests(unittest.TestCase):
    def test_research_agent_execute_schema_matches_expected_keys(self):
        client = MagicMock(spec=OpenCodeClient)
        client.run.return_value.stdout = json.dumps(
            {
                "recommended_topic": "Micro-content trends for creators",
                "audience_problem": "Creators struggle to convert engagement into meaningful growth.",
                "why_now": "Short-form video and carousel content are dominating discovery in 2026.",
                "hook": "Turn trend intelligence into reliable Instagram momentum.",
                "supporting_points": ["Point 1", "Point 2"],
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
                "identity": "brain/identity.md",
                "strategy": "brain/strategy.md",
                "prompt": "research.md",
            })
        finally:
            db.close()

        self.assertIn("recommended_topic", result)
        self.assertIn("audience_problem", result)
        self.assertIn("why_now", result)
        self.assertIn("hook", result)
        self.assertIn("supporting_points", result)
        self.assertIn("confidence", result)
        self.assertIn("reasoning", result)
        self.assertIn("timestamp", result)

    def test_planner_agent_execute_returns_placeholder(self):
        agent = PlannerAgent()
        result = agent.execute({"research_output": {"recommended_topic": "trend-a"}})

        self.assertIn("ideas", result)
        self.assertIn("selected_idea", result)

    def test_creator_agent_execute_returns_placeholder(self):
        agent = CreatorAgent()
        result = agent.execute({
            "selected_idea": {"idea": "Create a post about trend-a", "score": 0.8},
            "identity": "identity.md",
            "constitution": "constitution.md",
            "strategy": "strategy.md",
        })

        self.assertIn("carousel_outline", result)
        self.assertIn("caption", result)
        self.assertIn("cta", result)
        self.assertIn("hashtags", result)
        self.assertIn("image_prompt", result)

    def test_reviewer_agent_execute_returns_placeholder(self):
        agent = ReviewerAgent()
        result = agent.execute({"creator_output": {"caption": "A placeholder caption."}})

        self.assertIn("status", result)
        self.assertIn("reasons", result)
        self.assertIn("timestamp", result)


if __name__ == "__main__":
    unittest.main()
