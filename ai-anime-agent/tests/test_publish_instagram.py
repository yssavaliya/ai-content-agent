import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from ai_content_agent.publish.instagram import (
    InstagramAPIError,
    InstagramGraphClient,
    InstagramPublisher,
    build_caption,
)
from tests.helpers import base_env


class BuildCaptionTests(unittest.TestCase):
    def test_build_caption_appends_hashtags(self):
        caption = build_caption("Hello there", ["#a", "#b"])
        self.assertIn("#a", caption)
        self.assertIn("#b", caption)
        self.assertTrue(caption.startswith("Hello there"))

    def test_build_caption_truncates_to_2200(self):
        caption = build_caption("x" * 3000, ["#tag"])
        self.assertLessEqual(len(caption), 2200)


class InstagramGraphClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = InstagramGraphClient("test-token", api_version="21.0")

    @patch("ai_content_agent.publish.instagram.requests.post")
    def test_create_image_container(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"id": "container-1"})
        result = self.client.create_image_container(
            "111", "https://example.com/img.jpg", "caption", "alt"
        )
        self.assertEqual(result, "container-1")
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["data"]["image_url"], "https://example.com/img.jpg")
        self.assertEqual(kwargs["data"]["caption"], "caption")
        self.assertEqual(kwargs["data"]["alt_text"], "alt")

    @patch("ai_content_agent.publish.instagram.requests.get")
    def test_container_status(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200, json=lambda: {"status_code": "FINISHED"})
        self.assertEqual(self.client.container_status("c1"), "FINISHED")

    @patch("ai_content_agent.publish.instagram.requests.post")
    def test_publish_container(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"id": "media-9"})
        self.assertEqual(self.client.publish_container("111", "c1"), "media-9")

    @patch("ai_content_agent.publish.instagram.requests.post")
    def test_raises_on_api_error(self, mock_post):
        response = MagicMock(status_code=400, text='{"error":{"code":190}}')
        response.json.return_value = {"error": {"code": 190, "error_subcode": 33}}
        mock_post.return_value = response
        with self.assertRaises(InstagramAPIError) as ctx:
            self.client.create_image_container("111", "url")
        self.assertEqual(ctx.exception.code, 190)

    @patch("ai_content_agent.publish.instagram.requests.get")
    def test_wait_for_container_returns_when_finished(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200, json=lambda: {"status_code": "FINISHED"})
        self.client.wait_for_container("c1")

    @patch("ai_content_agent.publish.instagram.requests.get")
    def test_wait_for_container_raises_on_error(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200, json=lambda: {"status_code": "ERROR"})
        with self.assertRaises(InstagramAPIError):
            self.client.wait_for_container("c1")

    @patch("ai_content_agent.publish.instagram.requests.get")
    def test_wait_for_container_raises_on_expired(self, mock_get):
        mock_get.return_value = MagicMock(status_code=200, json=lambda: {"status_code": "EXPIRED"})
        with self.assertRaises(InstagramAPIError):
            self.client.wait_for_container("c1")


class InstagramPublisherTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_env = dict(os.environ)
        os.environ.update(base_env())
        self._temp_dir = tempfile.TemporaryDirectory()
        self.package_path = Path(self._temp_dir.name) / "package.json"
        self.package_path.write_text(
            json.dumps(
                {
                    "image": {"media_url": "https://example.com/img.jpg", "file_path": "x.png"},
                    "creation": {
                        "caption": "A caption",
                        "hashtags": ["#a", "#b"],
                        "alt_text": "An image description",
                    },
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._original_env)
        self._temp_dir.cleanup()

    def test_publish_returns_media_id(self):
        client = MagicMock(spec=InstagramGraphClient)
        client.create_image_container.return_value = "container-1"
        client.wait_for_container.return_value = None
        client.publish_container.return_value = "media-9"

        publisher = InstagramPublisher(access_token="tok", account_id="111", client=client)
        result = publisher.publish(str(self.package_path))

        self.assertEqual(result.provider, "instagram")
        self.assertEqual(result.status, "published")
        self.assertEqual(result.published_id, "media-9")
        self.assertEqual(result.metadata["container_id"], "container-1")
        client.create_image_container.assert_called_once()
        client.publish_container.assert_called_once()

    def test_publish_raises_without_public_url(self):
        self.package_path.write_text(json.dumps({"image": {}, "creation": {}}), encoding="utf-8")
        publisher = InstagramPublisher(access_token="tok", account_id="111", client=MagicMock())
        with self.assertRaises(InstagramAPIError):
            publisher.publish(str(self.package_path))

    def test_publish_requires_client_credentials(self):
        os.environ["INSTAGRAM_PUBLISH_ENABLED"] = "true"
        os.environ.pop("INSTAGRAM_ACCESS_TOKEN", None)
        publisher = InstagramPublisher()
        with self.assertRaises(InstagramAPIError):
            publisher._get_client()


if __name__ == "__main__":
    unittest.main()
