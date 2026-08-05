import os
import unittest
from pathlib import Path

from ai_content_agent.providers.image.base import ImageRequest
from ai_content_agent.providers.image.registry import ImageProviderRegistry
from ai_content_agent.providers.image.mock_provider import MockImageProvider


class ImageProviderRegistryTests(unittest.TestCase):
    def test_provider_registration(self):
        self.assertIn("mock", ImageProviderRegistry.list_providers())
        provider_cls = ImageProviderRegistry.get_provider("mock")
        self.assertIs(provider_cls, MockImageProvider)

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


if __name__ == "__main__":
    unittest.main()
