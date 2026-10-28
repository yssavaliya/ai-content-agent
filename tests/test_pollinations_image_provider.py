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

    @patch("requests.get", side_effect=requests.RequestException("Network timeout"))
    def test_generate_fallback_to_pillow_on_network_error(self, mock_get: MagicMock) -> None:
        req = ImageRequest(
            prompt="Masterpiece anime key visual for Chrono Blade",
            brand_style="clean",
            aspect_ratio="1:1",
        )
        res = self.provider.generate(req)

        self.assertEqual(res.provider, "pillow")
        self.assertTrue(Path(res.file_path).exists())
        self.assertTrue(res.file_path.endswith(".png"))
