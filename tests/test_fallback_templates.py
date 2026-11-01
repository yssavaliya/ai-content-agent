import re
import unittest

from ai_content_agent.fallback.templates import THEMES, generate_post

REQUIRED = {"carousel_outline", "caption", "cta", "hashtags", "image_prompt", "alt_text"}


class TemplateGeneratorTests(unittest.TestCase):
    def test_same_inputs_give_the_same_post(self):
        self.assertEqual(generate_post("anime", "2026-11-02", 3), generate_post("anime", "2026-11-02", 3))

    def test_payload_matches_the_creator_schema(self):
        for theme in THEMES:
            with self.subTest(theme=theme):
                post = generate_post(theme, "2026-11-02")
                self.assertEqual(set(post), REQUIRED)
                self.assertTrue(post["caption"].strip() and post["cta"].strip() and post["alt_text"].strip())
                self.assertIsInstance(post["carousel_outline"], list)
                self.assertLessEqual(len(post["caption"]), 2200)

    def test_every_day_and_every_variant_differs(self):
        for theme in THEMES:
            with self.subTest(theme=theme):
                captions = {generate_post(theme, f"2026-11-{day:02d}", variant)["caption"] for day in range(1, 31) for variant in range(3)}
                self.assertEqual(len(captions), 90)

    def test_hashtags_are_valid_unique_and_sized_for_instagram(self):
        for variant in range(40):
            tags = generate_post("anime", "d", variant)["hashtags"]
            self.assertEqual(len(tags), len(set(tags)))
            self.assertTrue(7 <= len(tags) <= 9)
            self.assertTrue(all(re.fullmatch(r"#[a-z0-9]+", tag) for tag in tags), tags)

    def test_copy_contains_no_numbers_or_statistics(self):
        for theme in THEMES:
            for variant in range(60):
                post = generate_post(theme, "d", variant)
                self.assertIsNone(re.search(r"\d", post["caption"] + post["cta"]), post["caption"])

    def test_image_prompt_follows_the_strategy_formula(self):
        prompt = generate_post("anime", "d")["image_prompt"]
        self.assertIn("masterpiece anime key visual", prompt)
        self.assertIn("no text", prompt)  # no pagination or text overlays on the artwork

    def test_unknown_theme_is_rejected(self):
        with self.assertRaises(ValueError):
            generate_post("cooking", "d")


if __name__ == "__main__":
    unittest.main()
