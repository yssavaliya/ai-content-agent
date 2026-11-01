import contextlib
import io
import os
import tempfile
import unittest
from collections import Counter
from unittest.mock import MagicMock, patch

from ai_content_agent.cli import main
from ai_content_agent.publish.buffer_status import (
    BufferPost,
    BufferStatus,
    BufferStatusError,
    delete_posts,
    select_for_deletion,
)

DUP = "Building in the shadows before the breakthrough hits. Most people see autonomous systems as overnight success."


def post(pid, status, text, due="2026-11-12T04:51:00Z"):
    return BufferPost(pid, status, "addToQueue", due, None, text)


def status_of(posts):
    s = BufferStatus("chan", posts)
    s.by_status = Counter(p.status for p in posts)
    return s


def http(body, code=200):
    resp = MagicMock()
    resp.status_code = code
    resp.json.return_value = body
    resp.text = str(body)
    return resp


class SelectionSafetyTests(unittest.TestCase):
    def test_selects_matching_unsent_posts_case_and_whitespace_insensitively(self):
        s = status_of([post("a", "scheduled", DUP), post("b", "draft", "  BUILDING in the   shadows before the breakthrough hits. x"), post("c", "scheduled", "Something else entirely here")])
        self.assertEqual([p.id for p in select_for_deletion(s, "building in the shadows before the breakthrough")], ["a", "b"])

    def test_a_sent_post_is_never_selected_even_if_it_matches(self):
        s = status_of([post("a", "sent", DUP), post("b", "scheduled", DUP)])
        self.assertEqual([p.id for p in select_for_deletion(s, "Building in the shadows before")], ["b"])

    def test_a_short_or_empty_match_is_refused(self):
        s = status_of([post("a", "scheduled", DUP)])
        for match in ("", "shadows", "   a  b  "):
            with self.subTest(match=match):
                with self.assertRaises(BufferStatusError):
                    select_for_deletion(s, match)

    def test_matching_more_than_ten_posts_is_refused(self):
        s = status_of([post(str(i), "scheduled", DUP) for i in range(11)])
        with self.assertRaises(BufferStatusError):
            select_for_deletion(s, "Building in the shadows before")

    def test_no_match_selects_nothing(self):
        self.assertEqual(select_for_deletion(status_of([post("a", "scheduled", DUP)]), "text that no post contains"), [])


class DeleteTests(unittest.TestCase):
    def test_success_failure_and_error_are_reported_per_post(self):
        answers = {
            "a": http({"data": {"deletePost": {"__typename": "DeletePostSuccess", "id": "a"}}}),
            "b": http({"data": {"deletePost": {"__typename": "VoidMutationError"}}}),
            "c": http({"errors": [{"message": "Not allowed"}]}),
        }

        def fake(url, json=None, headers=None, timeout=None):
            return answers[json["variables"]["input"]["id"]]

        posts = [post(i, "scheduled", DUP) for i in "abc"]
        results = delete_posts("tok", posts, post=fake)
        self.assertEqual([(r[0].id, r[1]) for r in results], [("a", True), ("b", False), ("c", False)])
        self.assertIn("VoidMutationError", results[1][2])
        self.assertIn("Not allowed", results[2][2])

    def test_only_the_delete_mutation_is_sent_with_the_post_id(self):
        sent = []

        def fake(url, json=None, headers=None, timeout=None):
            sent.append(json)
            return http({"data": {"deletePost": {"__typename": "DeletePostSuccess", "id": "a"}}})

        delete_posts("tok", [post("a", "scheduled", DUP)], post=fake)
        self.assertIn("mutation DeletePost", sent[0]["query"])
        self.assertEqual(sent[0]["variables"], {"input": {"id": "a"}})


class CliTests(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self.tmp = tempfile.TemporaryDirectory()
        os.chdir(self.tmp.name)
        self._env = patch.dict(
            os.environ,
            {"LOG_LEVEL": "WARNING", "DATABASE_PATH": ":memory:", "OPENCODE_COMMAND": "o", "INSTAGRAM_ENABLED": "false",
             "IMAGE_PROVIDER": "local", "BUFFER_ACCESS_TOKEN": "tok", "BUFFER_PROFILE_ID": "chan"},
            clear=True,
        )
        self._env.start()
        self.state = status_of([post("a1234567", "scheduled", DUP), post("b7654321", "sent", DUP), post("c1111111", "scheduled", "Different post text goes here")])

    def tearDown(self):
        self._env.stop()
        os.chdir(self._cwd)
        self.tmp.cleanup()

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_default_is_a_dry_run_that_deletes_nothing(self):
        with patch("ai_content_agent.publish.buffer_status.fetch_status", return_value=self.state), patch(
            "ai_content_agent.publish.buffer_status.delete_posts"
        ) as delete:
            code, out, _ = self.run_cli("buffer-delete", "--match", "Building in the shadows before the breakthrough")
        self.assertEqual(code, 0)
        self.assertIn("1 unsent post(s) match", out)
        self.assertIn("Dry run", out)
        delete.assert_not_called()

    def test_yes_deletes_only_the_selected_unsent_posts(self):
        with patch("ai_content_agent.publish.buffer_status.fetch_status", return_value=self.state), patch(
            "ai_content_agent.publish.buffer_status.delete_posts",
            side_effect=lambda token, posts: [(p, True, "deleted") for p in posts],
        ) as delete:
            code, out, _ = self.run_cli("buffer-delete", "--match", "Building in the shadows before the breakthrough", "--yes")
        self.assertEqual(code, 0)
        self.assertEqual([p.id for p in delete.call_args.args[1]], ["a1234567"])  # not the sent one, not the other post
        self.assertIn("deleted", out)

    def test_missing_match_and_refused_matches_exit_nonzero(self):
        self.assertEqual(self.run_cli("buffer-delete")[0], 2)
        with patch("ai_content_agent.publish.buffer_status.fetch_status", return_value=self.state):
            code, _, err = self.run_cli("buffer-delete", "--match", "short")
        self.assertEqual(code, 1)
        self.assertIn("at least 15 characters", err)


if __name__ == "__main__":
    unittest.main()
