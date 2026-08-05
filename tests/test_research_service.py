import os
import unittest
from datetime import datetime
from typing import Any

from ai_content_agent.research.provider import ResearchProvider, ResearchTrend
from ai_content_agent.research.service import ResearchService


class DummyResearchProvider(ResearchProvider):
    @property
    def name(self) -> str:
        return "dummy"

    def fetch_trends(self) -> list[ResearchTrend]:
        return [
            ResearchTrend(
                provider=self.name,
                title="Topic A",
                source="source-a",
                summary="Summary A",
                category="Category A",
                url="https://example.com/a",
                retrieved_at=datetime.utcnow().isoformat() + "Z",
                raw_payload={"source": "a"},
            ),
            ResearchTrend(
                provider=self.name,
                title="Topic B",
                source="source-b",
                summary="Summary B",
                category="Category B",
                url="https://example.com/b",
                retrieved_at=datetime.utcnow().isoformat() + "Z",
                raw_payload={"source": "b"},
            ),
        ]


class FailingResearchProvider(ResearchProvider):
    @property
    def name(self) -> str:
        return "failing"

    def fetch_trends(self) -> list[ResearchTrend]:
        raise RuntimeError("failure")


class ResearchServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_env = dict(os.environ)
        os.environ.update(
            {
                "LOG_LEVEL": "DEBUG",
                "DATABASE_PATH": ":memory:",
                "OPENCODE_COMMAND": "opencode",
                "INSTAGRAM_ENABLED": "false",
                "IMAGE_PROVIDER": "local",
            }
        )

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._original_env)

    def test_collect_returns_ranked_trends(self):
        service = ResearchService([DummyResearchProvider()])
        trends = service.collect()

        self.assertEqual(len(trends), 2)
        self.assertEqual(trends[0].title, "Topic A")
        self.assertEqual(trends[1].title, "Topic B")

    def test_collect_continues_when_provider_fails(self):
        service = ResearchService([DummyResearchProvider(), FailingResearchProvider()])
        trends = service.collect()

        self.assertEqual(len(trends), 2)

    def test_persist_raw_inserts_records(self):
        service = ResearchService([DummyResearchProvider()])
        trends = service.collect()
        service.persist_raw(trends)

        self.assertTrue(trends)


if __name__ == "__main__":
    unittest.main()
