import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ai_content_agent.opencode.client import OpenCodeClient, OpenCodeError
from ai_content_agent.opencode.recorder import PromptRecorder

REQUIRED_ENV = {
    "LOG_LEVEL": "INFO",
    "DATABASE_PATH": "agent.db",
    "OPENCODE_COMMAND": "opencode",
    "INSTAGRAM_ENABLED": "false",
    "IMAGE_PROVIDER": "local",
}


class OpenCodeClientFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_env = dict(os.environ)
        self._tmp = tempfile.TemporaryDirectory()
        self.logs_dir = Path(self._tmp.name) / "logs" / "prompts"
        os.environ.update(REQUIRED_ENV)

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._old_env)
        self._tmp.cleanup()

    def _raise_file_not_found(self, *args, **kwargs):
        raise FileNotFoundError("opencode not installed")

    def test_reraises_when_no_api_key(self):
        os.environ.pop("OPENAI_API_KEY", None)
        client = OpenCodeClient(recorder=PromptRecorder(logs_dir=self.logs_dir))
        with patch("ai_content_agent.opencode.client.subprocess.Popen", side_effect=self._raise_file_not_found):
            with self.assertRaises(OpenCodeError):
                client.run([], input_text="prompt", label="ResearchAgent")

    def test_reraises_when_fallback_disabled(self):
        os.environ["OPENAI_API_KEY"] = "sk-test"
        os.environ["OPENAI_TEXT_FALLBACK_ENABLED"] = "false"
        client = OpenCodeClient(recorder=PromptRecorder(logs_dir=self.logs_dir))
        with patch("ai_content_agent.opencode.client.subprocess.Popen", side_effect=self._raise_file_not_found):
            with self.assertRaises(OpenCodeError):
                client.run([], input_text="prompt", label="ResearchAgent")

    def test_falls_back_to_openai_when_opencode_missing(self):
        os.environ["OPENAI_API_KEY"] = "sk-test"
        os.environ["OPENAI_TEXT_MODEL"] = "gpt-4o-mini"
        fake_openai = MagicMock()
        fake_openai.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"topic": "AI"}'))]
        )
        client = OpenCodeClient(
            recorder=PromptRecorder(logs_dir=self.logs_dir),
            openai_client=fake_openai,
        )
        with patch("ai_content_agent.opencode.client.subprocess.Popen", side_effect=self._raise_file_not_found):
            result = client.run([], input_text="prompt", label="ResearchAgent")
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(json.loads(result.stdout), {"topic": "AI"})
        fake_openai.chat.completions.create.assert_called_once()
        kwargs = fake_openai.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-4o-mini")

    def test_fallback_strips_markdown_fences(self):
        os.environ["OPENAI_API_KEY"] = "sk-test"
        fake_openai = MagicMock()
        fake_openai.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='```json\n{"a": 1}\n```'))]
        )
        client = OpenCodeClient(
            recorder=PromptRecorder(logs_dir=self.logs_dir),
            openai_client=fake_openai,
        )
        with patch("ai_content_agent.opencode.client.subprocess.Popen", side_effect=self._raise_file_not_found):
            result = client.run([], input_text="prompt", label="PlannerAgent")
        self.assertEqual(json.loads(result.stdout), {"a": 1})

    def test_reraises_when_openai_fallback_fails(self):
        os.environ["OPENAI_API_KEY"] = "sk-test"
        fake_openai = MagicMock()
        fake_openai.chat.completions.create.side_effect = RuntimeError("api down")
        client = OpenCodeClient(
            recorder=PromptRecorder(logs_dir=self.logs_dir),
            openai_client=fake_openai,
        )
        with patch("ai_content_agent.opencode.client.subprocess.Popen", side_effect=self._raise_file_not_found):
            with self.assertRaises(OpenCodeError):
                client.run([], input_text="prompt", label="ResearchAgent")


if __name__ == "__main__":
    unittest.main()
