import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from ai_content_agent.agents.predictor import PredictorAgent
from ai_content_agent.database.connection import DatabaseConnection
from ai_content_agent.opencode.client import OpenCodeClient, OpenCodeError
from ai_content_agent.prompts.manager import PromptManager

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

PREDICTION_OUTPUT = {
    "virality_score": 82,
    "virality_label": "HIGH",
    "virality_probability": 0.7,
    "key_factors": ["Strong hook", "Trend-aligned topic"],
    "risks": ["Festival season competition"],
    "reasoning": "High score because the topic is trend-aligned.",
    "timestamp": "2026-08-05T00:00:00Z",
}


class PredictorAgentTests(unittest.TestCase):
    def _inputs(self) -> dict[str, object]:
        return {
            "creator_output": CREATOR_OUTPUT,
            "research_json": "{}",
            "review_json": "{}",
            "recent_posts_json": "[]",
            "market": str(Path("brain/market.md")),
        }

    def test_execute_returns_valid_prediction(self):
        client = MagicMock(spec=OpenCodeClient)
        client.run.return_value.stdout = json.dumps(PREDICTION_OUTPUT)

        db = DatabaseConnection(db_path=":memory:")
        try:
            agent = PredictorAgent(
                opencode_client=client,
                prompt_manager=PromptManager(prompt_dir=Path("src/ai_content_agent/prompts")),
                database=db,
            )
            result = agent.execute(self._inputs())
        finally:
            db.close()

        self.assertEqual(result["virality_score"], 82)
        self.assertEqual(result["virality_label"], "HIGH")
        self.assertEqual(len(result["key_factors"]), 2)

    def test_execute_raises_on_out_of_range_score(self):
        client = MagicMock(spec=OpenCodeClient)
        client.run.return_value.stdout = json.dumps({**PREDICTION_OUTPUT, "virality_score": 150})

        db = DatabaseConnection(db_path=":memory:")
        try:
            agent = PredictorAgent(
                opencode_client=client,
                prompt_manager=PromptManager(prompt_dir=Path("src/ai_content_agent/prompts")),
                database=db,
            )
            with self.assertRaises(RuntimeError):
                agent.execute(self._inputs())
        finally:
            db.close()

        self.assertEqual(client.run.call_count, 2)

    def test_execute_raises_on_malformed_json(self):
        client = MagicMock(spec=OpenCodeClient)
        client.run.return_value.stdout = "{invalid json}"

        db = DatabaseConnection(db_path=":memory:")
        try:
            agent = PredictorAgent(
                opencode_client=client,
                prompt_manager=PromptManager(prompt_dir=Path("src/ai_content_agent/prompts")),
                database=db,
            )
            with self.assertRaises(RuntimeError):
                agent.execute(self._inputs())
        finally:
            db.close()

    def test_execute_retries_on_timeout(self):
        client = MagicMock(spec=OpenCodeClient)
        client.run.side_effect = [
            OpenCodeError("timeout", -1, "", ""),
            MagicMock(stdout=json.dumps(PREDICTION_OUTPUT)),
        ]

        db = DatabaseConnection(db_path=":memory:")
        try:
            agent = PredictorAgent(
                opencode_client=client,
                prompt_manager=PromptManager(prompt_dir=Path("src/ai_content_agent/prompts")),
                database=db,
            )
            result = agent.execute(self._inputs())
        finally:
            db.close()

        self.assertEqual(result["virality_score"], 82)
        self.assertEqual(client.run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
