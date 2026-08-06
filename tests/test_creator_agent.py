import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from ai_content_agent.agents.creator import CreatorAgent
from ai_content_agent.database.connection import DatabaseConnection
from ai_content_agent.opencode.client import OpenCodeClient, OpenCodeError
from ai_content_agent.prompts.manager import PromptManager

VALID_OUTPUT = {
    "carousel_outline": [
        "Slide 1: Open with the audience problem and the hook.",
        "Slide 2: Explain why this trend matters now.",
        "Slide 3: Share a practical step-by-step framework.",
        "Slide 4: Recap with a clear call to action.",
    ],
    "caption": "Trend intelligence only works when you turn it into a repeatable system. Here is the exact framework we use to turn research into momentum.",
    "cta": "Save this post and follow for more research-driven content strategy.",
    "hashtags": ["#contentstrategy", "#creatoreconomy", "#instagramtips"],
    "image_prompt": "A clean carousel cover image with bold typography reading 'Turn Trends Into Momentum', using a minimal modern layout.",
    "alt_text": "A minimalist carousel cover with bold text 'Turn Trends Into Momentum' on a light gradient background.",
}


class CreatorAgentTests(unittest.TestCase):
    def test_execute_returns_valid_creator_output(self):
        client = MagicMock(spec=OpenCodeClient)
        client.run.return_value.stdout = json.dumps(VALID_OUTPUT)

        db = DatabaseConnection(db_path=":memory:")
        try:
            agent = CreatorAgent(
                opencode_client=client,
                prompt_manager=PromptManager(prompt_dir=Path("src/ai_content_agent/prompts")),
                database=db,
            )
            result = agent.execute({
                "selected_idea": {"idea": "Turn trend intelligence into a repeatable carousel series"},
                "identity": str(Path("brain/identity.md")),
                "constitution": str(Path("brain/constitution.md")),
                "strategy": str(Path("brain/strategy.md")),
            })
        finally:
            db.close()

        self.assertEqual(len(result["carousel_outline"]), 4)
        self.assertEqual(result["alt_text"], VALID_OUTPUT["alt_text"])
        self.assertEqual(result["hashtags"], VALID_OUTPUT["hashtags"])

    def test_execute_raises_on_malformed_json(self):
        client = MagicMock(spec=OpenCodeClient)
        client.run.return_value.stdout = "{invalid json}"

        db = DatabaseConnection(db_path=":memory:")
        try:
            agent = CreatorAgent(
                opencode_client=client,
                prompt_manager=PromptManager(prompt_dir=Path("src/ai_content_agent/prompts")),
                database=db,
            )
            with self.assertRaises(RuntimeError):
                agent.execute({
                    "selected_idea": {"idea": "An idea"},
                    "identity": str(Path("brain/identity.md")),
                    "constitution": str(Path("brain/constitution.md")),
                    "strategy": str(Path("brain/strategy.md")),
                })
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
            agent = CreatorAgent(
                opencode_client=client,
                prompt_manager=PromptManager(prompt_dir=Path("src/ai_content_agent/prompts")),
                database=db,
            )
            result = agent.execute({
                "selected_idea": {"idea": "An idea"},
                "identity": str(Path("brain/identity.md")),
                "constitution": str(Path("brain/constitution.md")),
                "strategy": str(Path("brain/strategy.md")),
            })
        finally:
            db.close()

        self.assertEqual(result["caption"], VALID_OUTPUT["caption"])

    def test_execute_raises_on_schema_validation_failure(self):
        client = MagicMock(spec=OpenCodeClient)
        client.run.return_value.stdout = json.dumps(
            {
                "carousel_outline": [],
                "caption": "",
                "cta": "",
                "hashtags": [],
                "image_prompt": "",
                "alt_text": "",
            }
        )

        db = DatabaseConnection(db_path=":memory:")
        try:
            agent = CreatorAgent(
                opencode_client=client,
                prompt_manager=PromptManager(prompt_dir=Path("src/ai_content_agent/prompts")),
                database=db,
            )
            with self.assertRaises(RuntimeError):
                agent.execute({
                    "selected_idea": {"idea": "An idea"},
                    "identity": str(Path("brain/identity.md")),
                    "constitution": str(Path("brain/constitution.md")),
                    "strategy": str(Path("brain/strategy.md")),
                })
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
