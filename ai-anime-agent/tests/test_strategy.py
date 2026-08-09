import tempfile
import unittest
from pathlib import Path

from ai_content_agent.database.connection import DatabaseConnection
from ai_content_agent.science.strategy import StrategyGovernance

STRONG_RECOMMENDATION = {
    "strategy_guideline": "Prefer concise captions under 90 characters.",
    "rationale": "Concise captions drove materially higher engagement.",
    "variable": "caption-length",
    "observed_effect": 0.8,
    "sample_size": 24,
    "confidence": 0.9,
}

WEAK_RECOMMENDATION = {
    "strategy_guideline": "Use emojis in every post.",
    "rationale": "Slightly higher engagement observed.",
    "variable": "emoji-use",
    "observed_effect": 0.05,
    "sample_size": 3,
    "confidence": 0.4,
}


class StrategyGovernanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.strategy_path = Path(self._temp_dir.name) / "strategy.md"
        self.strategy_path.write_text("# Brand Strategy\n", encoding="utf-8")
        self.db = DatabaseConnection(db_path=":memory:")

    def tearDown(self) -> None:
        self.db.close()
        self._temp_dir.cleanup()

    def _governance(self) -> StrategyGovernance:
        return StrategyGovernance(
            strategy_path=self.strategy_path,
            database=self.db,
            min_sample_size=10,
            min_effect=0.15,
            apply_threshold=0.6,
        )

    def test_strong_recommendation_is_applied(self):
        outcome = self._governance().apply_recommendation(STRONG_RECOMMENDATION, trigger="scientist")
        self.assertTrue(outcome["applied"])
        self.assertIn(STRONG_RECOMMENDATION["strategy_guideline"], self.strategy_path.read_text(encoding="utf-8"))

        row = self.db.execute("SELECT trigger, new_text FROM strategy_history").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "scientist")
        self.assertIn(STRONG_RECOMMENDATION["strategy_guideline"], row[1])

    def test_weak_recommendation_is_rejected(self):
        outcome = self._governance().apply_recommendation(WEAK_RECOMMENDATION, trigger="scientist")
        self.assertFalse(outcome["applied"])
        self.assertIn("reason", outcome)
        self.assertNotIn(WEAK_RECOMMENDATION["strategy_guideline"], self.strategy_path.read_text(encoding="utf-8"))

    def test_duplicate_guideline_is_rejected(self):
        governance = self._governance()
        first = governance.apply_recommendation(STRONG_RECOMMENDATION, trigger="scientist")
        second = governance.apply_recommendation(STRONG_RECOMMENDATION, trigger="scientist")
        self.assertTrue(first["applied"])
        self.assertFalse(second["applied"])
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM strategy_history").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
