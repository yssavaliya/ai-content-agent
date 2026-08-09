import base64
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from ai_content_agent.providers.image.base import ImageRequest
from ai_content_agent.providers.image.exceptions import ImageProviderError
from ai_content_agent.providers.image.local_provider import LocalImageProvider
from ai_content_agent.providers.image.mock_provider import MockImageProvider
from ai_content_agent.providers.image.openai_provider import OpenAIImageProvider
from ai_content_agent.providers.image.registry import ImageProviderRegistry


class ImageProviderRegistryTests(unittest.TestCase):
    def test_provider_registration(self):
        self.assertIn("mock", ImageProviderRegistry.list_providers())
        provider_cls = ImageProviderRegistry.get_provider("mock")
        self.assertIs(provider_cls, MockImageProvider)

    def test_openai_provider_registration(self):
        self.assertIn("openai", ImageProviderRegistry.list_providers())
        provider_cls = ImageProviderRegistry.get_provider("openai")
        self.assertIs(provider_cls, OpenAIImageProvider)

    def test_mock_provider_generate(self):
        provider = MockImageProvider()
        request = ImageRequest(prompt="A test prompt", brand_style="clean", aspect_ratio="1:1")
        result = provider.generate(request)

        self.assertEqual(result.provider, "mock")
        self.assertTrue(Path(result.file_path).exists())
        self.assertEqual(result.prompt, request.prompt)

    def test_mock_provider_validation_fails(self):
        provider = MockImageProvider()
        request = ImageRequest(prompt="", brand_style="clean", aspect_ratio="1:1")

        with self.assertRaises(ValueError):
            provider.generate(request)


class LocalImageProviderTests(unittest.TestCase):
    def test_local_provider_registration(self):
        self.assertIn("local", ImageProviderRegistry.list_providers())
        provider_cls = ImageProviderRegistry.get_provider("local")
        self.assertIs(provider_cls, LocalImageProvider)

    def test_local_provider_writes_prompt_text_file(self):
        provider = LocalImageProvider()
        request = ImageRequest(prompt="A test prompt", brand_style="clean", aspect_ratio="1:1")
        result = provider.generate(request)

        self.assertEqual(result.provider, "local")
        self.assertTrue(result.file_path.endswith(".txt"))
        path = Path(result.file_path)
        self.assertTrue(path.exists())
        content = path.read_text(encoding="utf-8")
        self.assertIn("A test prompt", content)
        self.assertIn("clean", content)
        self.assertIn("1:1", content)
        self.assertEqual(result.prompt, request.prompt)

    def test_local_provider_validation_fails(self):
        provider = LocalImageProvider()
        request = ImageRequest(prompt="", brand_style="clean", aspect_ratio="1:1")

        with self.assertRaises(ValueError):
            provider.generate(request)


class OpenAIImageProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self._api_key = os.environ.pop("OPENAI_API_KEY", None)

    def tearDown(self) -> None:
        if self._api_key is not None:
            os.environ["OPENAI_API_KEY"] = self._api_key

    def test_openai_provider_generate_writes_png(self):
        image_bytes = b"\x89PNG\r\n\x1a\nfake-png-bytes"
        client = MagicMock()
        client.images.generate.return_value = SimpleNamespace(
            data=[
                SimpleNamespace(
                    b64_json=base64.b64encode(image_bytes).decode("ascii"),
                    revised_prompt="A refined version of the prompt",
                )
            ]
        )

        provider = OpenAIImageProvider(api_key="test-key", client=client)
        request = ImageRequest(prompt="A test prompt", brand_style="clean", aspect_ratio="1:1")
        result = provider.generate(request)

        self.assertEqual(result.provider, "openai")
        self.assertTrue(Path(result.file_path).exists())
        self.assertEqual(Path(result.file_path).read_bytes(), image_bytes)
        self.assertEqual(result.metadata["model"], "gpt-image-1")
        self.assertEqual(result.metadata["size"], "1024x1024")
        self.assertIn("created_at", result.metadata)

    def test_openai_provider_uses_aspect_ratio_size(self):
        client = MagicMock()
        client.images.generate.return_value = SimpleNamespace(
            data=[SimpleNamespace(b64_json=base64.b64encode(b"bytes").decode("ascii"), revised_prompt=None)]
        )

        provider = OpenAIImageProvider(api_key="test-key", client=client)
        request = ImageRequest(prompt="A test prompt", brand_style="clean", aspect_ratio="4:5")
        result = provider.generate(request)

        self.assertEqual(result.metadata["size"], "1024x1280")

    def test_openai_provider_raises_without_key_or_client(self):
        provider = OpenAIImageProvider()

        with self.assertRaises(ImageProviderError):
            provider.generate(ImageRequest(prompt="A test prompt", brand_style="clean", aspect_ratio="1:1"))

    def test_openai_provider_validation_fails(self):
        provider = OpenAIImageProvider(api_key="test-key", client=MagicMock())
        request = ImageRequest(prompt="", brand_style="clean", aspect_ratio="1:1")

        with self.assertRaises(ValueError):
            provider.generate(request)


if __name__ == "__main__":
    unittest.main()
