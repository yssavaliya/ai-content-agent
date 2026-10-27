import unittest
from pathlib import Path

from PIL import Image

from ai_content_agent.providers.image.base import ImageRequest
from ai_content_agent.providers.image.pillow_provider import PillowImageProvider
from ai_content_agent.providers.image.registry import ImageProviderRegistry
from ai_content_agent.publish.hosting import convert_to_jpeg


class PillowImageProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = PillowImageProvider()

    def test_registered_in_registry(self) -> None:
        self.assertIn("pillow", ImageProviderRegistry.list_providers())
        provider_cls = ImageProviderRegistry.get_provider("pillow")
        self.assertIs(provider_cls, PillowImageProvider)

    def test_generate_square_1_1_creates_real_png(self) -> None:
        req = ImageRequest(
            prompt="Masterpiece anime key visual for 'Chrono Blade', cyberpunk setting",
            brand_style="clean",
            aspect_ratio="1:1",
        )
        res = self.provider.generate(req)

        self.assertEqual(res.provider, "pillow")
        self.assertTrue(Path(res.file_path).exists())
        self.assertTrue(res.file_path.endswith(".png"))

        with Image.open(res.file_path) as img:
            self.assertEqual(img.format, "PNG")
            self.assertEqual(img.size, (1080, 1080))
            self.assertEqual(img.mode, "RGB")

    def test_generate_portrait_4_5_dimensions(self) -> None:
        req = ImageRequest(
            prompt="Masterpiece anime key visual for 'Sky Garden', vertical composition",
            brand_style="clean",
            aspect_ratio="4:5",
        )
        res = self.provider.generate(req)

        with Image.open(res.file_path) as img:
            self.assertEqual(img.format, "PNG")
            self.assertEqual(img.size, (1080, 1350))

    def test_generate_landscape_16_9_dimensions(self) -> None:
        req = ImageRequest(
            prompt="Cinematic anime panorama of Neo-Varanasi",
            brand_style="clean",
            aspect_ratio="16:9",
        )
        res = self.provider.generate(req)

        with Image.open(res.file_path) as img:
            self.assertEqual(img.format, "PNG")
            self.assertEqual(img.size, (1920, 1080))

    def test_validation_fails_on_empty_prompt(self) -> None:
        req = ImageRequest(prompt="", brand_style="clean", aspect_ratio="1:1")
        with self.assertRaises(ValueError):
            self.provider.generate(req)

    def test_validation_fails_on_unsupported_aspect_ratio(self) -> None:
        req = ImageRequest(prompt="Valid prompt", brand_style="clean", aspect_ratio="21:9")
        with self.assertRaises(ValueError):
            self.provider.generate(req)

    def test_convert_to_jpeg_compatibility(self) -> None:
        req = ImageRequest(
            prompt="Key visual artwork for Instagram publish conversion test",
            brand_style="clean",
            aspect_ratio="1:1",
        )
        res = self.provider.generate(req)

        out_jpeg = Path("images") / "jpeg" / "test_pillow_convert.jpg"
        converted = convert_to_jpeg(res.file_path, out_jpeg)

        self.assertTrue(converted.exists())
        self.assertLessEqual(converted.stat().st_size, 8 * 1024 * 1024)

        with Image.open(converted) as img:
            self.assertEqual(img.format, "JPEG")
            self.assertEqual(img.size, (1080, 1080))


if __name__ == "__main__":
    unittest.main()
