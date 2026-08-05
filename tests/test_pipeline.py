import os
import unittest
from pathlib import Path

from ai_content_agent.application.pipeline import ContentPipeline


class PipelineTests(unittest.TestCase):
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

    def test_run_pipeline_generates_package(self):
        pipeline = ContentPipeline()
        result = pipeline.run()

        self.assertIn("research", result)
        self.assertIn("planning", result)
        self.assertIn("creation", result)
        self.assertIn("review", result)
        self.assertIn("image", result)
        self.assertIn("publish", result)
        self.assertTrue(Path("posts").exists())


if __name__ == "__main__":
    unittest.main()
