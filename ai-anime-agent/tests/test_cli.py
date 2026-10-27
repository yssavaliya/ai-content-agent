import contextlib
import io
import os
import tempfile
import unittest
from unittest.mock import patch

from ai_content_agent.cli import main


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        # No environment and no .env file: a fresh clone before configuration.
        self._cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)
        self._env = patch.dict(os.environ, {}, clear=True)
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()
        os.chdir(self._cwd)
        self._tmp.cleanup()

    def _run(self, *args: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_help_needs_no_configuration(self):
        code, out, _ = self._run("help")
        self.assertEqual(code, 0)
        self.assertIn("Usage: ai-content-agent", out)

    def test_unknown_command_exits_2_without_configuration(self):
        code, _, err = self._run("bogus")
        self.assertEqual(code, 2)
        self.assertIn("Unknown command: bogus", err)

    def test_missing_configuration_is_a_clean_error(self):
        code, _, err = self._run("daily")
        self.assertEqual(code, 1)
        self.assertIn("Missing required configuration values", err)
        self.assertNotIn("Traceback", err)


if __name__ == "__main__":
    unittest.main()
