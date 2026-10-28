import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from ai_content_agent.publish.buffer import BufferPublisher
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
            "success": True,
            "updates": [{"id": "buffer_update_12345"}],
        }
        mock_post.return_value = mock_resp

        publisher = BufferPublisher(access_token="tok_123", profile_id="prof_456")
        res = publisher.publish(str(self.package_path))

        self.assertEqual(res.provider, "buffer")
        self.assertEqual(res.status, "published")
        self.assertEqual(res.published_id, "buffer_update_12345")
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["data"]["access_token"], "tok_123")
        self.assertEqual(kwargs["data"]["profile_ids[]"], "prof_456")
        self.assertIn("Test viral caption", kwargs["data"]["text"])
        self.assertEqual(kwargs["data"]["media[photo]"], "https://raw.githubusercontent.com/test/repo/main/images/test.jpg")

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
        settings.instagram_publish_enabled = False

        publisher = PublishRegistry.build_publisher(settings)
        self.assertIsInstance(publisher, BufferPublisher)
        self.assertEqual(publisher.access_token, "tok_buf")
        self.assertEqual(publisher.profile_id, "prof_buf")
