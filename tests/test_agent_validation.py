import unittest

from ai_content_agent.agents.predictor import PredictorAgent
from ai_content_agent.agents.research import ResearchAgent
from ai_content_agent.agents.reviewer import ReviewerAgent


class TimestampIsNotRequiredFromTheModelTests(unittest.TestCase):
    """The agents stamp the time themselves, so an otherwise valid answer must not be rejected without one."""

    def test_reviewer_accepts_and_stamps(self):
        out = ReviewerAgent()._validate_payload({"status": "PASS", "reasons": ["fine"]})
        self.assertTrue(out["timestamp"].endswith("Z"))

    def test_predictor_accepts_and_stamps(self):
        out = PredictorAgent()._validate_payload(
            {
                "virality_score": 60,
                "virality_label": "MEDIUM",
                "virality_probability": 0.5,
                "key_factors": ["a"],
                "risks": ["b"],
                "reasoning": "c",
            }
        )
        self.assertTrue(out["timestamp"].endswith("Z"))

    def test_research_accepts_and_replaces_the_models_clock(self):
        payload = {
            "recommended_topic": "t",
            "audience_problem": "p",
            "why_now": "w",
            "hook": "h",
            "supporting_points": ["s"],
            "trend_signals": ["x"],
            "candidate_topics": ["c"],
            "confidence": 70,
            "reasoning": "r",
        }
        self.assertTrue(ResearchAgent()._validate_payload(dict(payload))["timestamp"].endswith("Z"))
        wrong_clock = ResearchAgent()._validate_payload(dict(payload, timestamp="2024-01-01T00:00:00Z"))
        self.assertNotEqual(wrong_clock["timestamp"], "2024-01-01T00:00:00Z")

    def test_the_other_required_fields_are_still_enforced(self):
        with self.assertRaises(ValueError):
            ReviewerAgent()._validate_payload({"status": "PASS"})
        with self.assertRaises(ValueError):
            ReviewerAgent()._validate_payload({"status": "MAYBE", "reasons": ["x"]})


if __name__ == "__main__":
    unittest.main()
