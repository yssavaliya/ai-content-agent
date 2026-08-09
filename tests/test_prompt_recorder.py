import json
import tempfile
import unittest
from pathlib import Path

from ai_content_agent.diagnostics.prompt_viewer import generate_html
from ai_content_agent.opencode.client import strip_markdown_fences
from ai_content_agent.opencode.recorder import PromptRecorder


class StripMarkdownFencesTests(unittest.TestCase):
    def test_strips_json_fence(self):
        text = '```json\n{"a": 1}\n```'
        self.assertEqual(strip_markdown_fences(text), '{"a": 1}')

    def test_strips_plain_fence(self):
        text = '```\nhello world\n```'
        self.assertEqual(strip_markdown_fences(text), "hello world")

    def test_passthrough_without_fence(self):
        text = '{"a": 1}'
        self.assertEqual(strip_markdown_fences(text), text)


class PromptRecorderTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.logs_dir = Path(self._tmp.name) / "logs" / "prompts"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_start_writes_prompt_file(self):
        recorder = PromptRecorder(logs_dir=self.logs_dir)
        path = recorder.start("hello prompt", "ResearchAgent", "abc123")
        self.assertTrue(path.exists())
        self.assertEqual(path.read_text(encoding="utf-8"), "hello prompt")
        self.assertIn("abc123", path.name)
        self.assertIn("ResearchAgent", path.name)

    def test_finish_writes_metadata_sidecar(self):
        recorder = PromptRecorder(logs_dir=self.logs_dir)
        path = recorder.start("hello prompt", "PlannerAgent", "abc123")
        meta_path = recorder.finish(path, elapsed_seconds=1.25, exit_code=0)
        self.assertTrue(meta_path.exists())
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["exit_code"], 0)
        self.assertEqual(metadata["elapsed_seconds"], 1.25)

    def test_label_is_sanitized(self):
        recorder = PromptRecorder(logs_dir=self.logs_dir)
        path = recorder.start("hello prompt", "Bad/Label with spaces!", "abc123")
        self.assertNotIn("/", path.name)
        self.assertNotIn(" ", path.name)


class PromptViewerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.logs_dir = Path(self._tmp.name) / "logs" / "prompts"
        self.logs_dir.mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_generate_html_includes_entries(self):
        recorder = PromptRecorder(logs_dir=self.logs_dir)
        prompt_path = recorder.start('{"topic": "AI"}', "ResearchAgent", "abc123")
        recorder.finish(prompt_path, elapsed_seconds=2.0, exit_code=0)

        output = generate_html(logs_dir=self.logs_dir, output=self.logs_dir / "index.html")
        self.assertTrue(output.exists())
        content = output.read_text(encoding="utf-8")
        self.assertIn("Prompt Viewer", content)
        self.assertIn("abc123", content)
        self.assertIn("<details>", content)

    def test_generate_html_with_no_prompts(self):
        output = generate_html(logs_dir=self.logs_dir, output=self.logs_dir / "index.html")
        self.assertTrue(output.exists())
        content = output.read_text(encoding="utf-8")
        self.assertIn("Prompt Viewer", content)


if __name__ == "__main__":
    unittest.main()
