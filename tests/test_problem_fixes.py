import logging
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_content_agent.agents.planner import PlannerAgent
from ai_content_agent.database.connection import initialize_database
from ai_content_agent.growth.dedupe import find_similar_reference, strategy_examples
from ai_content_agent.llm.chain import ProviderChain, ProviderHealth, demote_recently_failing
from ai_content_agent.llm.errors import AUTH, ProviderError
from ai_content_agent.llm.providers import Completion

GOOD = '{"ok": true}'


class Scripted:
    supports_json_mode = True
    records_own_usage = True

    def __init__(self, name, *outcomes):
        self.name, self.outcomes = name, list(outcomes)

    def complete(self, prompt, json_mode, timeout):
        outcome = self.outcomes.pop(0) if self.outcomes else GOOD
        if isinstance(outcome, Exception):
            raise outcome
        return Completion(outcome, model="m")


SCORES = {"educational_score": 0.8, "originality_score": 0.7, "engagement_score": 0.9, "relevance_score": 0.6}


class PlannerMissingScoreTests(unittest.TestCase):
    def test_scores_dropped_from_selected_idea_are_copied_from_the_matching_idea(self):
        payload = {
            "ideas": [{"idea": "Hook formulas", **SCORES}, {"idea": "Other", **SCORES}],
            "selected_idea": {"idea": "hook  formulas", "reasoning": "best"},
        }
        out = PlannerAgent()._validate_payload(payload)
        self.assertEqual(out["selected_idea"]["educational_score"], 0.8)
        self.assertEqual(out["selected_idea"]["relevance_score"], 0.6)

    def test_nothing_is_invented_when_there_is_no_matching_idea(self):
        payload = {"ideas": [{"idea": "A", **SCORES}], "selected_idea": {"idea": "Totally different"}}
        with self.assertRaises(ValueError) as ctx:
            PlannerAgent()._validate_payload(payload)
        self.assertIn("selected_idea.educational_score", str(ctx.exception))

    def test_complete_payloads_are_untouched(self):
        payload = {"ideas": [{"idea": "A", **SCORES}], "selected_idea": {"idea": "A", **SCORES, "total_score": 3.0}}
        self.assertEqual(PlannerAgent()._validate_payload(payload)["selected_idea"]["total_score"], 3.0)


class StrategyExampleTests(unittest.TestCase):
    STRATEGY = (
        '- Hook: *"The world only celebrates the awakening. They never see the ten thousand hours in the shadows."*\n'
        '- CTA: *"Drop a sword in the comments if you are locking into your craft today!"*\n'
        '- short *"too short"*\n'
    )

    def examples(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "strategy.md"
            path.write_text(self.STRATEGY, encoding="utf-8")
            return strategy_examples(path)

    def test_quoted_examples_are_extracted_and_short_ones_ignored(self):
        examples = self.examples()
        self.assertEqual(len(examples), 2)
        self.assertTrue(examples[0].startswith("The world only celebrates"))

    def test_missing_strategy_file_gives_no_examples(self):
        self.assertEqual(strategy_examples("does-not-exist.md"), [])

    def test_a_caption_that_contains_an_example_sentence_is_a_copy(self):
        examples = self.examples()
        caption = (
            "The world only celebrates the awakening. They never see the ten thousand hours in the shadows.\n\n"
            "- Silent grit fuels the brightest glows.\n- Shadows are the forge of mastery."
        )
        hit = find_similar_reference(caption, examples)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.score, 1.0)

    def test_original_captions_pass(self):
        caption = "Ever wondered why the silent hours matter?\n\n- The night is a canvas for unseen practice."
        self.assertIsNone(find_similar_reference(caption, self.examples()))


class DemotionByLatestCallsTests(unittest.TestCase):
    def order(self, rows):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "agent.db"
            initialize_database(db)
            connection = sqlite3.connect(db)
            for provider, ok in rows:  # oldest first
                connection.execute(
                    "INSERT INTO api_usage(created_at, service, operation, provider, ok) "
                    "VALUES (strftime('%Y-%m-%dT%H:%M:%SZ','now'), 'llm', 'chat', ?, ?)",
                    (provider, ok),
                )
            connection.commit()
            connection.close()
            providers = [Scripted("gemini"), Scripted("pollinations")]
            return [p.name for p in demote_recently_failing(providers, str(db))]

    def test_a_provider_that_worked_before_but_failed_its_last_three_calls_is_demoted(self):
        self.assertEqual(self.order([("gemini", 1), ("gemini", 0), ("gemini", 0), ("gemini", 0)]), ["pollinations", "gemini"])

    def test_one_success_among_the_latest_three_keeps_the_order(self):
        self.assertEqual(self.order([("gemini", 0), ("gemini", 0), ("gemini", 1), ("gemini", 0)]), ["gemini", "pollinations"])

    def test_too_little_evidence_keeps_the_order(self):
        self.assertEqual(self.order([("gemini", 0), ("gemini", 0)]), ["gemini", "pollinations"])


class FailedAttemptLogTests(unittest.TestCase):
    def test_skipped_providers_are_not_counted_as_failed_attempts(self):
        health = ProviderHealth()
        health.disable("dead", "quota")
        chain = ProviderChain([Scripted("dead"), Scripted("good")], health=health, sleep=lambda s: None)
        with self.assertLogs("ai_content_agent.llm.chain", level=logging.INFO) as logs:
            chain.complete("p")
        message = " ".join(logs.output)
        self.assertIn("answered by good", message)
        self.assertNotIn("failed attempt", message)

    def test_real_failures_are_counted(self):
        chain = ProviderChain(
            [Scripted("bad", ProviderError(AUTH, "x")), Scripted("good")], health=ProviderHealth(), sleep=lambda s: None
        )
        with self.assertLogs("ai_content_agent.llm.chain", level=logging.INFO) as logs:
            chain.complete("p")
        self.assertIn("after 1 failed attempt(s)", " ".join(logs.output))


if __name__ == "__main__":
    with patch("builtins.print"):
        unittest.main()
