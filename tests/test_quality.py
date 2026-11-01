import unittest

from ai_content_agent.application.pipeline import ContentPipeline as Pipeline
from ai_content_agent.growth.quality import lint_caption

GOOD = "Nobody claps for the silent hours.\n\nYet every legend is built inside them.\n\nDrop a flame if you agree"


class LintCaptionTests(unittest.TestCase):
    def test_a_normal_caption_passes(self):
        self.assertEqual(lint_caption(GOOD, ["#anime", "#animeart", "#digitalart"]), [])

    def test_empty_caption_is_rejected(self):
        self.assertEqual(lint_caption("  ", []), ["The caption is empty."])

    def test_famous_quotes_are_caught_through_punctuation_and_case(self):
        problems = lint_caption("BE THE CHANGE, you wish to see in the world!", [])
        self.assertEqual(len(problems), 1)
        self.assertIn("famous quote", problems[0])
        self.assertTrue(lint_caption("You miss 100% of the shots you don't take", []))

    def test_overlong_hook_too_many_tags_and_emojis_are_reported(self):
        hook = "word " * 40
        self.assertTrue(any("first line" in p for p in lint_caption(hook, [])))
        self.assertTrue(any("hashtags" in p for p in lint_caption(GOOD, [f"#t{i}" for i in range(20)])))
        self.assertTrue(any("hashtags" in p for p in lint_caption(GOOD + " #a #b #c #d #e #f", [])))
        self.assertTrue(any("emojis" in p for p in lint_caption(GOOD + " 🔥🔥🔥🔥🔥🔥🔥", [])))

    def test_short_generic_phrases_are_not_flagged(self):
        self.assertEqual(lint_caption("Knowledge is power only when you share it.", []), [])


class ApplyLintTests(unittest.TestCase):
    def test_pass_becomes_fail_with_the_problems_appended(self):
        draft = {"caption": "Be the change you wish to see.", "hashtags": [], "source": "llm"}
        out = Pipeline._apply_quality_lint(draft, {"status": "PASS", "reasons": ["ok"]})
        self.assertEqual(out["status"], "FAIL")
        self.assertEqual(out["reasons"][0], "ok")
        self.assertIn("famous quote", out["reasons"][1])

    def test_fail_and_fixed_templates_are_left_alone(self):
        quoted = {"caption": "Be the change you wish to see.", "hashtags": [], "source": "llm"}
        fail = {"status": "FAIL", "reasons": ["bad"]}
        self.assertIs(Pipeline._apply_quality_lint(quoted, fail), fail)
        template = dict(quoted, source="procedural_fallback")
        passed = {"status": "PASS", "reasons": []}
        self.assertIs(Pipeline._apply_quality_lint(template, passed), passed)


if __name__ == "__main__":
    unittest.main()
