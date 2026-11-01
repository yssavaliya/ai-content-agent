import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from ai_content_agent.agents.reviewer import ReviewerAgent
from ai_content_agent.cli import main
from ai_content_agent.publish.buffer import BufferPublisher
from ai_content_agent.publish.buffer_status import BufferStatusError, fetch_status, render
from ai_content_agent.publish.provider import PublishUnavailable

LIMIT_MESSAGE = "Scheduled posts limit reached. You have 10 scheduled posts out of 10 allowed."


def http(body, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = body
    resp.text = json.dumps(body)
    return resp


class BufferRefusalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.package = Path(self.tmp.name) / "package.json"
        self.package.write_text(
            json.dumps({"image": {"media_url": "https://example.com/a.jpg"}, "creation": {"caption": "c", "hashtags": []}}),
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    @patch("ai_content_agent.publish.buffer.requests.post")
    def test_a_full_queue_in_the_mutation_result_is_a_publish_refusal(self, post):
        post.return_value = http({"data": {"createPost": {"message": LIMIT_MESSAGE}}})
        with self.assertRaises(PublishUnavailable) as ctx:
            BufferPublisher("tok", "chan").publish(str(self.package))
        self.assertIn("10 scheduled posts out of 10", str(ctx.exception))

    @patch("ai_content_agent.publish.buffer.requests.post")
    def test_a_full_queue_in_the_errors_list_is_a_publish_refusal(self, post):
        post.return_value = http({"errors": [{"message": LIMIT_MESSAGE}]})
        with self.assertRaises(PublishUnavailable):
            BufferPublisher("tok", "chan").publish(str(self.package))

    @patch("ai_content_agent.publish.buffer.requests.post")
    def test_other_errors_are_still_failures_not_refusals(self, post):
        post.return_value = http({"data": {"createPost": {"message": "Something else broke"}}})
        with self.assertRaises(RuntimeError) as ctx:
            BufferPublisher("tok", "chan").publish(str(self.package))
        self.assertNotIsInstance(ctx.exception, PublishUnavailable)

    @patch("ai_content_agent.publish.buffer.requests.post")
    def test_a_mode_error_still_falls_back_to_the_queue(self, post):
        post.side_effect = [
            http({"data": {"createPost": {"message": "shareNow mode is not available on your plan"}}}),
            http({"data": {"createPost": {"post": {"id": "p1", "status": "scheduled"}}}}),
        ]
        result = BufferPublisher("tok", "chan").publish(str(self.package))
        self.assertEqual(result.status, "scheduled")


class BufferModeFallbackTests(unittest.TestCase):
    """The first-comment rejection used to skip straight to addToQueue, so nothing was ever shared now."""

    FIRST_COMMENT_MSG = "First comment is not available on your plan"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.package = Path(self.tmp.name) / "package.json"
        self.package.write_text(
            json.dumps({"image": {"media_url": "https://example.com/a.jpg"}, "creation": {"caption": "c", "hashtags": [], "cta": "Save"}}),
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def ok(status):
        return http({"data": {"createPost": {"post": {"id": "p1", "status": status}}}})

    @staticmethod
    def rejected(message):
        return http({"data": {"createPost": {"message": message}}})

    def sent_inputs(self, post):
        return [call.kwargs["json"]["variables"]["input"] for call in post.call_args_list]

    @patch("ai_content_agent.publish.buffer.requests.post")
    def test_first_comment_rejection_retries_share_now_without_the_comment(self, post):
        post.side_effect = [self.rejected(self.FIRST_COMMENT_MSG), self.ok("sent")]
        result = BufferPublisher("tok", "chan").publish(str(self.package))
        first, second = self.sent_inputs(post)
        self.assertEqual((first["mode"], second["mode"]), ("shareNow", "shareNow"))  # NOT addToQueue
        self.assertIn("firstComment", first["metadata"]["instagram"])
        self.assertNotIn("firstComment", second["metadata"]["instagram"])
        self.assertEqual(result.status, "sent")

    @patch("ai_content_agent.publish.buffer.requests.post")
    def test_a_refused_share_now_falls_back_to_the_queue_and_says_why(self, post):
        post.side_effect = [self.rejected("Sharing now is not allowed right now"), self.ok("scheduled")]
        with self.assertLogs("ai_content_agent.publish.buffer", level="WARNING") as logs:
            result = BufferPublisher("tok", "chan").publish(str(self.package))
        self.assertEqual([i["mode"] for i in self.sent_inputs(post)], ["shareNow", "addToQueue"])
        self.assertEqual(result.status, "scheduled")
        self.assertIn("Sharing now is not allowed", " ".join(logs.output))

    @patch("ai_content_agent.publish.buffer.requests.post")
    def test_a_failed_custom_schedule_falls_back_whatever_the_reason(self, post):
        post.side_effect = [self.rejected("dueAt must be in the future"), self.ok("scheduled")]
        BufferPublisher("tok", "chan", schedule_time_utc="12:30").publish(str(self.package))
        inputs = self.sent_inputs(post)
        self.assertEqual([i["mode"] for i in inputs], ["customScheduled", "addToQueue"])
        self.assertIn("dueAt", inputs[0])
        self.assertNotIn("dueAt", inputs[1])

    @patch("ai_content_agent.publish.buffer.requests.post")
    def test_an_unknown_error_in_the_last_mode_is_still_a_failure(self, post):
        post.side_effect = [self.rejected("nope"), self.rejected("Image could not be downloaded")]
        with self.assertRaises(RuntimeError) as ctx:
            BufferPublisher("tok", "chan").publish(str(self.package))
        self.assertIn("Image could not be downloaded", str(ctx.exception))

    @patch("ai_content_agent.publish.buffer.requests.post")
    def test_a_plan_limit_is_reported_in_any_mode(self, post):
        post.return_value = self.rejected(LIMIT_MESSAGE)
        with self.assertRaises(PublishUnavailable):
            BufferPublisher("tok", "chan").publish(str(self.package))
        self.assertEqual(post.call_count, 1)  # no point trying other modes against a full queue


class ReviewerEmptyPassTests(unittest.TestCase):
    def test_pass_with_no_findings_is_valid(self):
        out = ReviewerAgent()._validate_payload({"status": "PASS", "reasons": [], "timestamp": "x"})
        self.assertEqual(out["reasons"], ["No issues found."])

    def test_fail_must_say_why(self):
        with self.assertRaises(ValueError):
            ReviewerAgent()._validate_payload({"status": "FAIL", "reasons": []})


class BufferStatusTests(unittest.TestCase):
    def fake_post(self, posts, has_more=False):
        def post(url, json=None, headers=None, timeout=None):
            if "organizations" in json["query"]:
                return http({"data": {"account": {"organizations": [{"id": "org1", "name": "o"}]}}})
            self.assertEqual(json["variables"]["input"]["filter"]["channelIds"], ["chan"])
            edges = [{"node": node} for node in posts]
            return http({"data": {"posts": {"edges": edges, "pageInfo": {"hasNextPage": has_more}}}})

        return post

    NODES = [
        {"id": "1", "status": "scheduled", "dueAt": None, "sentAt": None, "shareMode": "addToQueue", "text": "queued one"},
        {"id": "2", "status": "scheduled", "dueAt": "2026-11-02T12:30:00Z", "sentAt": None, "shareMode": "customScheduled", "text": "timed"},
        {"id": "3", "status": "sent", "dueAt": "2026-10-30T12:30:00Z", "sentAt": "2026-10-30T12:31:00Z", "shareMode": "shareNow", "text": "gone out"},
    ]

    def test_summarises_what_is_waiting_and_what_has_no_send_time(self):
        status = fetch_status("tok", "chan", post=self.fake_post(self.NODES))
        self.assertEqual(status.by_status["scheduled"], 2)
        self.assertEqual(len(status.waiting), 2)
        self.assertEqual([p.id for p in status.waiting_without_time], ["1"])
        text = render(status)
        self.assertIn("Waiting to be sent: 2, of which with no send time (dueAt empty): 1", text)
        self.assertIn("never go out", text)

    def test_markdown_output_has_a_table(self):
        status = fetch_status("tok", "chan", post=self.fake_post(self.NODES))
        self.assertIn("| scheduled | addToQueue | - | - | queued one |", render(status, markdown=True))

    def test_errors_are_reported_without_leaking_the_token(self):
        def failing(url, json=None, headers=None, timeout=None):
            raise requests.ConnectionError("failed calling with Bearer SECRET-TOKEN")

        with self.assertRaises(BufferStatusError) as ctx:
            fetch_status("SECRET-TOKEN", "chan", post=failing)
        self.assertNotIn("SECRET-TOKEN", str(ctx.exception))

    def test_graphql_errors_are_raised(self):
        def post(url, json=None, headers=None, timeout=None):
            return http({"errors": [{"message": "Not authorised"}]})

        with self.assertRaises(BufferStatusError):
            fetch_status("tok", "chan", post=post)

    def test_only_reads_never_mutates(self):
        queries = []

        def post(url, json=None, headers=None, timeout=None):
            queries.append(json["query"])
            return self.fake_post(self.NODES)(url, json, headers, timeout)

        fetch_status("tok", "chan", post=post)
        self.assertTrue(all("mutation" not in q.lower() for q in queries))


class CliTests(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self.tmp = tempfile.TemporaryDirectory()
        os.chdir(self.tmp.name)
        self._env = patch.dict(
            os.environ,
            {"LOG_LEVEL": "WARNING", "DATABASE_PATH": ":memory:", "OPENCODE_COMMAND": "opencode", "INSTAGRAM_ENABLED": "false", "IMAGE_PROVIDER": "local"},
            clear=True,
        )
        self._env.start()

    def tearDown(self):
        self._env.stop()
        os.chdir(self._cwd)
        self.tmp.cleanup()

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_buffer_status_requires_credentials(self):
        code, _, err = self.run_cli("buffer-status")
        self.assertEqual(code, 2)
        self.assertIn("BUFFER_ACCESS_TOKEN", err)

    def test_blocked_publish_makes_the_daily_command_fail_visibly(self):
        package = {"publish": {"status": "blocked_publish", "metadata": {"reasons": [LIMIT_MESSAGE]}}}
        with patch("ai_content_agent.application.scheduler.Scheduler.run_daily", return_value={"package": package}):
            code, _, err = self.run_cli("daily")
        self.assertEqual(code, 1)
        self.assertIn("10 scheduled posts out of 10", err)


if __name__ == "__main__":
    unittest.main()
