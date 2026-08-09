import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

from ai_content_agent.agents.reviewer import ReviewerAgent
from ai_content_agent.database.connection import DatabaseConnection
from ai_content_agent.opencode.client import OpenCodeClient, OpenCodeError
from ai_content_agent.prompts.manager import PromptManager

CREATOR_OUTPUT = {
    "carousel_outline": [
        "Slide 1: Open with the audience problem.",
        "Slide 2: Explain why this trend matters now.",
    ],
    "caption": "A specific, on-brand caption about trend intelligence.",
    "cta": "Save this post and follow for more.",
    "hashtags": ["#contentstrategy", "#creatoreconomy"],
    "image_prompt": "A clean carousel cover image.",
    "alt_text": "A minimalist carousel cover image.",
}


class ReviewerAgentTests(unittest.TestCase):
    def _inputs(self) -> dict[str, object]:
        return {
            "creator_output": CREATOR_OUTPUT,
            "identity": str(Path("brain/identity.md")),
            "constitution": str(Path("brain/constitution.md")),
            "market": str(Path("brain/market.md")),
        }

    def test_execute_returns_valid_reviewer_output(self):
        client = MagicMock(spec=OpenCodeClient)
        client.run.return_value.stdout = json.dumps(
            {
                "status": "PASS",
                "reasons": [
                    "Grammar and spelling are correct.",
                    "Tone is consistent with the brand voice.",
                    "All carousel slides are present and the caption is specific.",
                ],
                "timestamp": "2026-08-05T00:00:00Z",
            }
        )

        db = DatabaseConnection(db_path=":memory:")
        try:
            agent = ReviewerAgent(
                opencode_client=client,
                prompt_manager=PromptManager(prompt_dir=Path("src/ai_content_agent/prompts")),
                database=db,
            )
            result = agent.execute(self._inputs())
        finally:
            db.close()

        self.assertEqual(result["status"], "PASS")
        self.assertGreaterEqual(len(result["reasons"]), 1)

    def test_execute_stamps_real_review_timestamp(self):
        client = MagicMock(spec=OpenCodeClient)
        before = datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"
        client.run.return_value.stdout = json.dumps(
            {
                "status": "FAIL",
                "reasons": ["Caption is too generic for the brand voice."],
                "timestamp": "2020-01-01T00:00:00Z",
            }
        )

        db = DatabaseConnection(db_path=":memory:")
        try:
            agent = ReviewerAgent(
                opencode_client=client,
                prompt_manager=PromptManager(prompt_dir=Path("src/ai_content_agent/prompts")),
                database=db,
            )
            result = agent.execute(self._inputs())
        finally:
            db.close()

        after = datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"
        self.assertGreaterEqual(result["timestamp"], before)
        self.assertLessEqual(result["timestamp"], after)
        self.assertNotEqual(result["timestamp"], "2020-01-01T00:00:00Z")

    def test_execute_raises_on_malformed_json(self):
        client = MagicMock(spec=OpenCodeClient)
        client.run.return_value.stdout = "{invalid json}"

        db = DatabaseConnection(db_path=":memory:")
        try:
            agent = ReviewerAgent(
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
            MagicMock(stdout=json.dumps(
                {
                    "status": "PASS",
                    "reasons": ["Draft meets brand and quality standards."],
                    "timestamp": "2026-08-05T00:00:00Z",
                }
            )),
        ]

        db = DatabaseConnection(db_path=":memory:")
        try:
            agent = ReviewerAgent(
                opencode_client=client,
                prompt_manager=PromptManager(prompt_dir=Path("src/ai_content_agent/prompts")),
                database=db,
            )
            result = agent.execute(self._inputs())
        finally:
            db.close()

        self.assertEqual(result["status"], "PASS")

    def test_execute_raises_on_schema_validation_failure(self):
        client = MagicMock(spec=OpenCodeClient)
        client.run.return_value.stdout = json.dumps(
            {
                "status": "MAYBE",
                "reasons": [],
                "timestamp": "",
            }
        )

        db = DatabaseConnection(db_path=":memory:")
        try:
            agent = ReviewerAgent(
                opencode_client=client,
                prompt_manager=PromptManager(prompt_dir=Path("src/ai_content_agent/prompts")),
                database=db,
            )
            with self.assertRaises(RuntimeError):
                agent.execute(self._inputs())
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
