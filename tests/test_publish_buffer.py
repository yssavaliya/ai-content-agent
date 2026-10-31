import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from ai_content_agent.publish.buffer import BufferPublisher, next_due_at
from ai_content_agent.publish.registry import PublishRegistry
from ai_content_agent.settings import Settings


class BufferPublisherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.package_path = Path(self.temp_dir.name) / "package.json"
        package_data = {
            "run_id": "test_run",
            "image": {
                "file_path": "images/test.png",
                "media_url": "https://raw.githubusercontent.com/test/repo/main/images/test.jpg",
            },
            "creation": {
                "caption": "Test viral caption",
                "cta": "Drop a ⚔️ in the comments!",
                "hashtags": ["#anime", "#art"],
                "alt_text": "Alt description",
            },
        }
        self.package_path.write_text(json.dumps(package_data), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @patch("ai_content_agent.publish.buffer.requests.post")
    def test_publish_success(self, mock_post: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": {
                "createPost": {
                    "post": {
                        "id": "buffer_update_12345",
                        "status": "published",
                    }
                }
            }
        }
        mock_post.return_value = mock_resp

        publisher = BufferPublisher(access_token="tok_123", profile_id="prof_456")
        res = publisher.publish(str(self.package_path))

        self.assertEqual(res.provider, "buffer")
        self.assertEqual(res.status, "published")
        self.assertEqual(res.published_id, "buffer_update_12345")
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer tok_123")
        self.assertIn("CreatePost", kwargs["json"]["query"])
        input_data = kwargs["json"]["variables"]["input"]
        self.assertEqual(input_data["channelId"], "prof_456")
        self.assertIn("Test viral caption", input_data["text"])
        self.assertEqual(input_data["assets"][0]["image"]["url"], "https://raw.githubusercontent.com/test/repo/main/images/test.jpg")
        self.assertEqual(input_data["metadata"]["instagram"]["type"], "post")
        self.assertIn("Drop your thoughts below", input_data["metadata"]["instagram"]["firstComment"])

    def test_publish_raises_if_media_url_missing(self) -> None:
        package_no_url = Path(self.temp_dir.name) / "no_url.json"
        package_no_url.write_text(json.dumps({"image": {}, "creation": {}}), encoding="utf-8")
        publisher = BufferPublisher(access_token="tok_123", profile_id="prof_456")
        with self.assertRaises(RuntimeError):
            publisher.publish(str(package_no_url))

    def test_registry_selects_buffer_when_tokens_configured(self) -> None:
        settings = MagicMock(spec=Settings)
        settings.buffer_access_token = "tok_buf"
        settings.buffer_profile_id = "prof_buf"
        settings.buffer_schedule_time_utc = None
        settings.instagram_publish_enabled = False

        publisher = PublishRegistry.build_publisher(settings)
        self.assertIsInstance(publisher, BufferPublisher)
        self.assertEqual(publisher.access_token, "tok_buf")
        self.assertEqual(publisher.profile_id, "prof_buf")
        self.assertIsNone(publisher.schedule_time_utc)

    @patch("ai_content_agent.publish.buffer.requests.post")
    def test_default_mode_shares_immediately_without_due_date(self, mock_post: MagicMock) -> None:
        mock_post.return_value = self._ok_response("scheduled")
        BufferPublisher(access_token="t", profile_id="p").publish(str(self.package_path))
        input_data = mock_post.call_args.kwargs["json"]["variables"]["input"]
        self.assertEqual(input_data["mode"], "shareNow")
        self.assertNotIn("dueAt", input_data)

    @patch("ai_content_agent.publish.buffer.requests.post")
    def test_schedule_time_sends_custom_scheduled_with_due_at(self, mock_post: MagicMock) -> None:
        mock_post.return_value = self._ok_response("scheduled")
        result = BufferPublisher(access_token="t", profile_id="p", schedule_time_utc="12:30").publish(
            str(self.package_path)
        )
        input_data = mock_post.call_args.kwargs["json"]["variables"]["input"]
        self.assertEqual(input_data["mode"], "customScheduled")
        self.assertRegex(input_data["dueAt"], r"^\d{4}-\d{2}-\d{2}T12:30:00Z$")
        self.assertEqual(result.metadata["due_at"], input_data["dueAt"])

    @staticmethod
    def _ok_response(status: str) -> MagicMock:
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"data": {"createPost": {"post": {"id": "b1", "status": status}}}}
        return response

    def test_next_due_at_picks_today_when_still_ahead(self) -> None:
        now = datetime(2026, 10, 31, 10, 0, tzinfo=timezone.utc)
        self.assertEqual(next_due_at(now, "12:30"), "2026-10-31T12:30:00Z")

    def test_next_due_at_rolls_to_tomorrow_when_passed_or_too_close(self) -> None:
        self.assertEqual(next_due_at(datetime(2026, 10, 31, 18, 6, tzinfo=timezone.utc), "12:30"), "2026-11-01T12:30:00Z")
        self.assertEqual(next_due_at(datetime(2026, 10, 31, 12, 27, tzinfo=timezone.utc), "12:30"), "2026-11-01T12:30:00Z")

    def test_invalid_schedule_time_is_rejected(self) -> None:
        for bad in ("25:00", "12", "ab:cd", "12:60"):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    BufferPublisher(access_token="t", profile_id="p", schedule_time_utc=bad)
