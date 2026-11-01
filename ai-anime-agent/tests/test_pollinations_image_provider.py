import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from ai_content_agent.providers.image.base import ImageRequest
from ai_content_agent.providers.image.pollinations_provider import (
    FluxImageProvider,
    PollinationsImageProvider,
)
from ai_content_agent.providers.image.registry import ImageProviderRegistry


class PollinationsImageProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = PollinationsImageProvider()

    def test_registered_in_registry(self) -> None:
        providers = ImageProviderRegistry.list_providers()
        self.assertIn("pollinations", providers)
        self.assertIn("flux", providers)
        self.assertIs(ImageProviderRegistry.get_provider("pollinations"), PollinationsImageProvider)
        self.assertIs(ImageProviderRegistry.get_provider("flux"), FluxImageProvider)

    def test_validate_empty_prompt_raises(self) -> None:
        req = ImageRequest(prompt="   ", brand_style="clean", aspect_ratio="1:1")
        with self.assertRaises(ValueError):
            self.provider.validate(req)

    def test_validate_unsupported_aspect_ratio_raises(self) -> None:
        req = ImageRequest(prompt="Valid prompt", brand_style="clean", aspect_ratio="3:2")
        with self.assertRaises(ValueError):
            self.provider.validate(req)

    def test_prompt_enhancement(self) -> None:
        raw = "Solo swordsman standing on a cliff"
        enhanced = self.provider._enhance_prompt(raw)
        self.assertIn("cinematic", enhanced)
        self.assertIn("8k resolution", enhanced)

        already_cinematic = "Cinematic 8k anime masterpiece of Neo Tokyo"
        self.assertEqual(self.provider._enhance_prompt(already_cinematic), already_cinematic)

    @patch("requests.get")
    def test_generate_success_saves_file(self, mock_get: MagicMock) -> None:
        fake_jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIFfake-image-bytes"
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = fake_jpeg
        mock_get.return_value = mock_response

        req = ImageRequest(
            prompt="Dramatic blood moon eclipse with lone swordsman silhouette",
            brand_style="clean",
            aspect_ratio="1:1",
        )
        res = self.provider.generate(req)

        self.assertEqual(res.provider, "pollinations")
        self.assertTrue(Path(res.file_path).exists())
        self.assertEqual(Path(res.file_path).read_bytes(), fake_jpeg)
        self.assertEqual(res.metadata["model"], "flux")
        self.assertEqual(res.metadata["dimensions"], "1080x1080")

    @patch("ai_content_agent.providers.image.pollinations_provider.time.sleep")
    @patch("requests.get", side_effect=requests.RequestException("Network timeout"))
    def test_generate_fallback_to_pillow_on_network_error(self, mock_get: MagicMock, mock_sleep: MagicMock) -> None:
        req = ImageRequest(
            prompt="Masterpiece anime key visual for Chrono Blade",
            brand_style="clean",
            aspect_ratio="1:1",
        )
        res = self.provider.generate(req)

        self.assertEqual(res.provider, "pillow")
        self.assertTrue(Path(res.file_path).exists())
        self.assertTrue(res.file_path.endswith(".png"))

class PollinationsImageRetryTests(unittest.TestCase):
    JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIFfake-image-bytes"

    def request(self) -> ImageRequest:
        return ImageRequest(prompt="Masterpiece anime key visual of a lone swordsman", brand_style="clean", aspect_ratio="1:1")

    @staticmethod
    def response(status: int, text: str = "", content: bytes = b"", headers: dict | None = None) -> MagicMock:
        resp = MagicMock()
        resp.status_code, resp.text, resp.content, resp.headers = status, text, content, headers or {}
        return resp

    @patch("ai_content_agent.providers.image.pollinations_provider.time.sleep")
    @patch("requests.get")
    def test_busy_service_is_waited_out_and_the_real_image_is_used(self, mock_get: MagicMock, mock_sleep: MagicMock) -> None:
        busy = self.response(503, '{"error":{"message":"The Classic API is at its limit right now. Retry after 10s"}}')
        mock_get.side_effect = [busy, self.response(200, content=self.JPEG)]
        result = PollinationsImageProvider().generate(self.request())
        self.assertEqual(result.provider, "pollinations")
        self.assertEqual(Path(result.file_path).read_bytes(), self.JPEG)
        mock_sleep.assert_called_once_with(10.0)  # honours the service's own "retry after"

    @patch("ai_content_agent.providers.image.pollinations_provider.time.sleep")
    @patch("requests.get")
    def test_retry_after_header_is_capped(self, mock_get: MagicMock, mock_sleep: MagicMock) -> None:
        mock_get.side_effect = [self.response(429, headers={"Retry-After": "900"}), self.response(200, content=self.JPEG)]
        PollinationsImageProvider().generate(self.request())
        mock_sleep.assert_called_once_with(30.0)

    @patch("ai_content_agent.providers.image.pollinations_provider.time.sleep")
    @patch("requests.get")
    def test_gives_up_after_max_attempts_and_falls_back_to_pillow(self, mock_get: MagicMock, mock_sleep: MagicMock) -> None:
        mock_get.return_value = self.response(503, "busy")
        result = PollinationsImageProvider(max_attempts=3).generate(self.request())
        self.assertEqual(result.provider, "pillow")
        self.assertEqual(mock_get.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)

    @patch("ai_content_agent.providers.image.pollinations_provider.time.sleep")
    @patch("requests.get")
    def test_client_errors_are_not_retried(self, mock_get: MagicMock, mock_sleep: MagicMock) -> None:
        mock_get.return_value = self.response(400, "bad prompt")
        result = PollinationsImageProvider().generate(self.request())
        self.assertEqual(result.provider, "pillow")
        self.assertEqual(mock_get.call_count, 1)
        mock_sleep.assert_not_called()

    @patch("requests.get")
    def test_without_fallback_the_failure_is_raised(self, mock_get: MagicMock) -> None:
        mock_get.return_value = self.response(404, "nope")
        from ai_content_agent.providers.image.exceptions import ImageProviderError

        with self.assertRaises(ImageProviderError):
            PollinationsImageProvider(fallback_to_pillow=False).generate(self.request())

