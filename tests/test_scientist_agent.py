import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from ai_content_agent.agents.scientist import ScientistAgent
from ai_content_agent.database.connection import DatabaseConnection
from ai_content_agent.opencode.client import OpenCodeClient
from ai_content_agent.prompts.manager import PromptManager

SCIENTIST_OUTPUT = {
    "recommendations": [
        {
            "strategy_guideline": "Prefer concise captions under 90 characters.",
            "rationale": "Concise captions drove materially higher engagement.",
            "variable": "caption-length",
            "observed_effect": 0.8,
            "sample_size": 24,
            "confidence": 0.9,
            "significance_p": 0.01,
        }
    ],
    "summary": "One recommendation cleared the evidence bar.",
}


class ScientistAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.inputs = {
            "experiment_results": [
                {
                    "experiment_id": 1,
                    "variable": "caption-length",
                    "cohens_d": 0.8,
                    "p_value": 0.01,
                    "n_control": 12,
                    "n_variant": 12,
                }
            ],
            "identity": "brain/identity.md",
            "constitution": "brain/constitution.md",
            "strategy": "brain/strategy.md",
        }

    def test_execute_returns_recommendations(self):
        client = MagicMock(spec=OpenCodeClient)
        client.run.return_value.stdout = json.dumps(SCIENTIST_OUTPUT)

        db = DatabaseConnection(db_path=":memory:")
        try:
            agent = ScientistAgent(
                opencode_client=client,
                prompt_manager=PromptManager(prompt_dir=Path("src/ai_content_agent/prompts")),
                database=db,
            )
            result = agent.execute(self.inputs)
        finally:
            db.close()

        self.assertEqual(len(result["recommendations"]), 1)
        self.assertEqual(result["recommendations"][0]["variable"], "caption-length")
        self.assertEqual(result["summary"], "One recommendation cleared the evidence bar.")

    def test_execute_allows_empty_recommendations(self):
        client = MagicMock(spec=OpenCodeClient)
        client.run.return_value.stdout = json.dumps(
            {"recommendations": [], "summary": "No evidence cleared the bar."}
        )

        db = DatabaseConnection(db_path=":memory:")
        try:
            agent = ScientistAgent(
                opencode_client=client,
                prompt_manager=PromptManager(prompt_dir=Path("src/ai_content_agent/prompts")),
                database=db,
            )
            result = agent.execute(self.inputs)
        finally:
            db.close()

        self.assertEqual(result["recommendations"], [])

    def test_execute_raises_on_schema_validation_failure(self):
        client = MagicMock(spec=OpenCodeClient)
        client.run.return_value.stdout = json.dumps(
            {
                "recommendations": [
                    {
                        "strategy_guideline": "",
                        "rationale": "",
                        "variable": "",
                        "observed_effect": "high",
                        "sample_size": "lots",
                        "confidence": "yes",
                        "significance_p": 0,
                    }
                ],
                "summary": "bad",
            }
        )

        db = DatabaseConnection(db_path=":memory:")
        try:
            agent = ScientistAgent(
                opencode_client=client,
                prompt_manager=PromptManager(prompt_dir=Path("src/ai_content_agent/prompts")),
                database=db,
            )
            with self.assertRaises(RuntimeError):
                agent.execute(self.inputs)
        finally:
            db.close()

    def test_execute_persists_analysis_observation(self):
        client = MagicMock(spec=OpenCodeClient)
        client.run.return_value.stdout = json.dumps(SCIENTIST_OUTPUT)

        db = DatabaseConnection(db_path=":memory:")
        try:
            agent = ScientistAgent(
                opencode_client=client,
                prompt_manager=PromptManager(prompt_dir=Path("src/ai_content_agent/prompts")),
                database=db,
            )
            agent.execute(self.inputs)

            row = db.execute(
                "SELECT source, metric_name, metric_value FROM observations"
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "ScientistAgent")
            self.assertEqual(row[1], "scientist_analysis")
            self.assertEqual(row[2], 1)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
