import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from ai_content_agent.publish.hosting import (
    GitHubRawImageHost,
    MediaHostingError,
    convert_to_jpeg,
    parse_repo,
    slugify,
)


class SlugifyTests(unittest.TestCase):
    def test_slugify_basic(self):
        self.assertEqual(slugify("Hello World!"), "hello-world")

    def test_slugify_empty(self):
        self.assertEqual(slugify("!!!"), "image")


class ParseRepoTests(unittest.TestCase):
    def test_parse_repo_valid(self):
        self.assertEqual(parse_repo("owner/repo"), ("owner", "repo"))

    def test_parse_repo_invalid(self):
        with self.assertRaises(MediaHostingError):
            parse_repo("no-slash")


class ConvertToJpegTests(unittest.TestCase):
    def test_convert_png_to_jpeg(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "input.png"
            target = Path(temp_dir) / "output.jpg"
            Image.new("RGBA", (200, 200), (255, 0, 0, 255)).save(source)

            result = convert_to_jpeg(source, target)

            self.assertEqual(result, target)
            self.assertTrue(target.exists())
            with Image.open(target) as image:
                self.assertEqual(image.format, "JPEG")
                self.assertIn(image.mode, ("RGB", "L"))


class GitHubRawImageHostTests(unittest.TestCase):
    def setUp(self) -> None:
        self.host = GitHubRawImageHost("owner/repo", "gh-token", branch="main", base_path="images")

    def test_public_url_format(self):
        self.assertEqual(
            self.host.public_url("images/abc/123.jpg"),
            "https://raw.githubusercontent.com/owner/repo/main/images/abc/123.jpg",
        )

    @patch("ai_content_agent.publish.hosting.requests.put")
    @patch("ai_content_agent.publish.hosting.requests.get")
    def test_upload_returns_hosted_image(self, mock_get, mock_put):
        mock_get.return_value = MagicMock(status_code=404)
        mock_put.return_value = MagicMock(
            status_code=201,
            json=lambda: {"content": {"sha": "abc123"}},
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "img.jpg"
            file_path.write_bytes(b"fake-jpeg")

            hosted = self.host.upload(file_path, "run1/img.jpg")

        self.assertEqual(
            hosted.url,
            "https://raw.githubusercontent.com/owner/repo/main/images/run1/img.jpg",
        )
        self.assertEqual(hosted.sha, "abc123")
        _, kwargs = mock_put.call_args
        body = kwargs["json"]
        self.assertEqual(body["branch"], "main")
        self.assertEqual(base64.b64decode(body["content"]), b"fake-jpeg")

    @patch("ai_content_agent.publish.hosting.requests.put")
    @patch("ai_content_agent.publish.hosting.requests.get")
    def test_upload_reuses_existing_sha(self, mock_get, mock_put):
        mock_get.return_value = MagicMock(status_code=200, json=lambda: {"sha": "old-sha"})
        mock_put.return_value = MagicMock(
            status_code=200,
            json=lambda: {"content": {"sha": "new-sha"}},
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "img.jpg"
            file_path.write_bytes(b"fake-jpeg")
            self.host.upload(file_path, "run1/img.jpg")

        _, kwargs = mock_put.call_args
        self.assertEqual(kwargs["json"]["sha"], "old-sha")

    @patch("ai_content_agent.publish.hosting.requests.put")
    @patch("ai_content_agent.publish.hosting.requests.get")
    def test_upload_raises_on_api_error(self, mock_get, mock_put):
        mock_get.return_value = MagicMock(status_code=404)
        mock_put.return_value = MagicMock(status_code=422, text="invalid content")

        with tempfile.TemporaryDirectory() as temp_dir:
            file_path = Path(temp_dir) / "img.jpg"
            file_path.write_bytes(b"fake-jpeg")
            with self.assertRaises(MediaHostingError):
                self.host.upload(file_path, "run1/img.jpg")


if __name__ == "__main__":
    unittest.main()
