import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from ai_content_agent.agents.planner import PlannerAgent
from ai_content_agent.database.connection import DatabaseConnection
from ai_content_agent.opencode.client import OpenCodeClient, OpenCodeError
from ai_content_agent.prompts.manager import PromptManager

VALID_OUTPUT = {
    "ideas": [
        {
            "idea": "Turn trend intelligence into a repeatable carousel series",
            "educational_score": 0.8,
            "originality_score": 0.7,
            "engagement_score": 0.9,
            "relevance_score": 0.9,
            "reasoning": "Directly extends the research topic and gives the audience a practical framework.",
        },
        {
            "idea": "Interview-style Q&A about content strategy trade-offs",
            "educational_score": 0.6,
            "originality_score": 0.8,
            "engagement_score": 0.7,
            "relevance_score": 0.6,
            "reasoning": "Interactive format with solid engagement potential.",
        },
        {
            "idea": "Before and after creator growth case study",
            "educational_score": 0.7,
            "originality_score": 0.6,
            "engagement_score": 0.8,
            "relevance_score": 0.7,
            "reasoning": "Concrete proof that resonates with the target audience.",
        },
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


class PlannerAgentTests(unittest.TestCase):
    def test_execute_returns_valid_planner_output(self):
        client = MagicMock(spec=OpenCodeClient)
        client.run.return_value.stdout = json.dumps(VALID_OUTPUT)

        db = DatabaseConnection(db_path=":memory:")
        try:
            agent = PlannerAgent(
                opencode_client=client,
                prompt_manager=PromptManager(prompt_dir=Path("src/ai_content_agent/prompts")),
                database=db,
            )
            result = agent.execute({"research_output": {"recommended_topic": "Trend X"}, "market": str(Path("brain/market.md"))})
        finally:
            db.close()

        self.assertEqual(len(result["ideas"]), 3)
        self.assertEqual(result["selected_idea"]["idea"], VALID_OUTPUT["selected_idea"]["idea"])
        self.assertEqual(result["selected_idea"]["total_score"], 3.3)

    def test_execute_raises_on_malformed_json(self):
        client = MagicMock(spec=OpenCodeClient)
        client.run.return_value.stdout = "{invalid json}"

        db = DatabaseConnection(db_path=":memory:")
        try:
            agent = PlannerAgent(
                opencode_client=client,
                prompt_manager=PromptManager(prompt_dir=Path("src/ai_content_agent/prompts")),
                database=db,
            )
            with self.assertRaises(RuntimeError):
                agent.execute({"research_output": {"recommended_topic": "Trend X"}, "market": str(Path("brain/market.md"))})
        finally:
            db.close()

    def test_execute_retries_on_timeout(self):
        client = MagicMock(spec=OpenCodeClient)
        client.run.side_effect = [
            OpenCodeError("timeout", -1, "", ""),
            MagicMock(stdout=json.dumps(VALID_OUTPUT)),
        ]

        db = DatabaseConnection(db_path=":memory:")
        try:
            agent = PlannerAgent(
                opencode_client=client,
                prompt_manager=PromptManager(prompt_dir=Path("src/ai_content_agent/prompts")),
                database=db,
            )
            result = agent.execute({"research_output": {"recommended_topic": "Trend X"}, "market": str(Path("brain/market.md"))})
        finally:
            db.close()

        self.assertEqual(result["selected_idea"]["idea"], VALID_OUTPUT["selected_idea"]["idea"])

    def test_execute_raises_on_schema_validation_failure(self):
        client = MagicMock(spec=OpenCodeClient)
        client.run.return_value.stdout = json.dumps(
            {
                "ideas": [
                    {
                        "idea": "",
                        "educational_score": "high",
                        "originality_score": 0.7,
                        "engagement_score": 0.9,
                        "relevance_score": 0.9,
                    }
                ],
                "selected_idea": {},
            }
        )

        db = DatabaseConnection(db_path=":memory:")
        try:
            agent = PlannerAgent(
                opencode_client=client,
                prompt_manager=PromptManager(prompt_dir=Path("src/ai_content_agent/prompts")),
                database=db,
            )
            with self.assertRaises(RuntimeError):
                agent.execute({"research_output": {"recommended_topic": "Trend X"}, "market": str(Path("brain/market.md"))})
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
