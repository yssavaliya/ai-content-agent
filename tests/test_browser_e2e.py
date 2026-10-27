from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ai_content_agent.diagnostics.prompt_viewer import generate_html
from ai_content_agent.opencode.recorder import PromptRecorder

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


class BrowserPromptViewerE2ETests(unittest.TestCase):
    """Browser-based end-to-end tests for the static Prompt Viewer using Playwright."""

    @classmethod
    def setUpClass(cls) -> None:
        if not PLAYWRIGHT_AVAILABLE:
            raise unittest.SkipTest("playwright is not installed")
        try:
            cls._pw = sync_playwright().start()
            cls._browser = cls._pw.chromium.launch(headless=True)
        except Exception as exc:
            if hasattr(cls, "_pw"):
                cls._pw.stop()
            raise unittest.SkipTest(f"Chromium browser could not be launched: {exc}")

        cls.screenshots_dir = Path("reports") / "screenshots"
        cls.screenshots_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "_browser"):
            cls._browser.close()
        if hasattr(cls, "_pw"):
            cls._pw.stop()

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.logs_dir = Path(self._tmp.name) / "logs" / "prompts"
        self.output_html = self.logs_dir / "index.html"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_browser_empty_state(self) -> None:
        generate_html(logs_dir=self.logs_dir, output=self.output_html)
        self.assertTrue(self.output_html.exists())

        page = self._browser.new_page()
        try:
            file_url = self.output_html.resolve().as_uri()
            page.goto(file_url)

            # Check title and header
            self.assertEqual(page.title(), "AI Content Agent - Prompt Viewer")
            header = page.locator("header h1")
            self.assertIn("AI Content Agent - Prompt Viewer", header.inner_text())

            # Check stats
            stats = page.locator(".stats")
            self.assertIn("0 prompts recorded", stats.inner_text())

            # Check empty state message
            empty = page.locator(".empty")
            self.assertTrue(empty.is_visible())
            self.assertIn("No prompt logs recorded yet", empty.inner_text())

            # Save diagnostic screenshot
            screenshot_path = self.screenshots_dir / "prompt_viewer_empty.png"
            page.screenshot(path=str(screenshot_path))
            self.assertTrue(screenshot_path.exists())
        finally:
            page.close()

    def test_browser_populated_interactive_state(self) -> None:
        recorder = PromptRecorder(logs_dir=self.logs_dir)

        # 1. Successful Research prompt
        p1 = recorder.start("Identity and Strategy prompt for ResearchAgent", "ResearchAgent", "run001")
        recorder.finish(p1, elapsed_seconds=2.45, exit_code=0, stdout_chars=520)

        # 2. Fallback Creator prompt
        p2 = recorder.start("Draft generation prompt for CreatorAgent", "CreatorAgent", "run001")
        recorder.finish(p2, elapsed_seconds=3.10, exit_code=0, error="fallback:gemini", stdout_chars=840)

        # 3. Failing Reviewer prompt
        p3 = recorder.start("Review prompt for ReviewerAgent", "ReviewerAgent", "run001")
        recorder.finish(p3, elapsed_seconds=1.20, exit_code=1, error="process exit 1", stderr_chars=120)

        generate_html(logs_dir=self.logs_dir, output=self.output_html)
        self.assertTrue(self.output_html.exists())

        page = self._browser.new_page()
        try:
            file_url = self.output_html.resolve().as_uri()
            page.goto(file_url)

            # Check stats
            stats = page.locator(".stats")
            self.assertIn("3 prompts recorded", stats.inner_text())

            # Verify badges
            ok_badge = page.locator(".badge-ok")
            self.assertTrue(ok_badge.is_visible())
            self.assertEqual(ok_badge.inner_text(), "ok")

            fb_badge = page.locator(".badge-fb")
            self.assertTrue(fb_badge.is_visible())
            self.assertEqual(fb_badge.inner_text(), "fallback")

            err_badge = page.locator(".badge-err")
            self.assertTrue(err_badge.is_visible())
            self.assertEqual(err_badge.inner_text(), "error")

            # Verify details cards and interaction (clicking summary expands pre)
            details_list = page.locator("details")
            self.assertEqual(details_list.count(), 3)

            first_summary = details_list.first.locator("summary")
            self.assertIn("ReviewerAgent", first_summary.inner_text())

            first_pre = details_list.first.locator("pre")
            # Initially closed details shouldn't display pre content
            self.assertFalse(first_pre.is_visible())

            # Click summary to expand
            first_summary.click()
            self.assertTrue(first_pre.is_visible())
            self.assertIn("Review prompt for ReviewerAgent", first_pre.inner_text())

            # Test mobile viewport responsiveness
            page.set_viewport_size({"width": 375, "height": 667})
            screenshot_mobile = self.screenshots_dir / "prompt_viewer_mobile.png"
            page.screenshot(path=str(screenshot_mobile))
            self.assertTrue(screenshot_mobile.exists())

            # Restore desktop and take populated screenshot
            page.set_viewport_size({"width": 1280, "height": 800})
            screenshot_path = self.screenshots_dir / "prompt_viewer_populated.png"
            page.screenshot(path=str(screenshot_path))
            self.assertTrue(screenshot_path.exists())
        finally:
            page.close()


if __name__ == "__main__":
    unittest.main()
