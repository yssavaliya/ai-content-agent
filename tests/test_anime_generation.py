import unittest
from unittest.mock import MagicMock

from ai_content_agent.anime.generator import (
    AnimeConcept,
    AnimeContentGenerator,
    AnimeScene,
    AnimeStoryOutline,
)
from ai_content_agent.opencode.client import OpenCodeClient, OpenCodeResult


class AnimeGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.generator = AnimeContentGenerator()

    def test_generate_concept_procedural_fallback(self) -> None:
        concept = self.generator.generate_concept("Quantum Samurai in Digital Tokyo")
        self.assertIsInstance(concept, AnimeConcept)
        self.assertIn("Quantum Samurai In Digital Tokyo", concept.title)
        self.assertEqual(concept.genre, "Supernatural Sci-Fi / Action")
        self.assertTrue(len(concept.synopsis) > 20)
        self.assertTrue(len(concept.setting) > 10)
        self.assertGreaterEqual(len(concept.themes), 1)

    def test_generate_concept_empty_theme_raises_error(self) -> None:
        with self.assertRaises(ValueError):
            self.generator.generate_concept("   ")

    def test_generate_characters_creates_distinct_roles(self) -> None:
        concept = self.generator.generate_concept("Solar Alchemists")
        chars = self.generator.generate_characters(concept, count=2)

        self.assertEqual(len(chars), 2)
        protagonist, deuteragonist = chars[0], chars[1]

        self.assertEqual(protagonist["role"], "Protagonist")
        self.assertEqual(deuteragonist["role"], "Deuteragonist")
        self.assertNotEqual(protagonist["name"], deuteragonist["name"])
        self.assertTrue(len(protagonist["motivation"]) > 5)
        self.assertTrue(len(deuteragonist["appearance"]) > 5)

    def test_generate_characters_invalid_count(self) -> None:
        concept = self.generator.generate_concept("Solar Alchemists")
        with self.assertRaises(ValueError):
            self.generator.generate_characters(concept, count=0)

    def test_generate_episode_outline_structure(self) -> None:
        concept = self.generator.generate_concept("Mecha Monsoon")
        chars = self.generator.generate_characters(concept, count=2)
        outline = self.generator.generate_episode_outline(concept, chars, episode_number=1)

        self.assertIsInstance(outline, AnimeStoryOutline)
        self.assertEqual(outline.episode_number, 1)
        self.assertIn("Episode 1", outline.episode_title)
        self.assertEqual(len(outline.scenes), 3)

        for scene in outline.scenes:
            self.assertIsInstance(scene, AnimeScene)
            self.assertGreater(scene.scene_number, 0)
            self.assertTrue(bool(scene.location))
            self.assertTrue(bool(scene.summary))
            self.assertGreater(len(scene.dialogue), 0)
            self.assertIn("speaker", scene.dialogue[0])
            self.assertIn("line", scene.dialogue[0])

        self.assertTrue(len(outline.cliffhanger) > 15)

    def test_generate_post_package_fields(self) -> None:
        concept = self.generator.generate_concept("Chai Shop Exorcists")
        chars = self.generator.generate_characters(concept, count=2)
        outline = self.generator.generate_episode_outline(concept, chars, episode_number=1)
        pkg = self.generator.generate_post_package(concept, outline, chars)

        self.assertIn("carousel_outline", pkg)
        self.assertIn("caption", pkg)
        self.assertIn("cta", pkg)
        self.assertIn("hashtags", pkg)
        self.assertIn("image_prompt", pkg)
        self.assertIn("alt_text", pkg)

        self.assertGreaterEqual(len(pkg["carousel_outline"]), 4)
        self.assertIn(concept.title, pkg["caption"])
        self.assertTrue(any("anime" in tag.lower() for tag in pkg["hashtags"]))
        self.assertIn("cinematic anime", pkg["image_prompt"].lower())

    def test_generator_with_llm_client_mock(self) -> None:
        mock_client = MagicMock(spec=OpenCodeClient)
        mock_client.run.return_value = OpenCodeResult(
            stdout="""```json
{
  "title": "Aether Knight Chronicles",
  "genre": "Fantasy / Adventure",
  "synopsis": "A wandering swordsman bonds with an ancient crystal dragon to protect the floating citadel.",
  "setting": "Floating realm of Celestia, ancient crystalline sky-islands.",
  "target_audience": "Shonen fans",
  "visual_style": "Luminous cel-shading with golden hour lighting",
  "themes": ["Loyalty", "Destiny"]
}
```""",
            stderr="",
            exit_code=0,
            elapsed_seconds=0.2,
        )

        gen = AnimeContentGenerator(opencode_client=mock_client)
        concept = gen.generate_concept("Crystal Dragon")

        self.assertEqual(concept.title, "Aether Knight Chronicles")
        self.assertEqual(concept.genre, "Fantasy / Adventure")
        self.assertEqual(concept.target_audience, "Shonen fans")


if __name__ == "__main__":
    unittest.main()
