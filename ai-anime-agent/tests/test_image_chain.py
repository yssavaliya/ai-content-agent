import base64
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests
from PIL import Image

from ai_content_agent.providers.image.auto_provider import AutoImageProvider
from ai_content_agent.providers.image.base import ImageRequest
from ai_content_agent.providers.image.cloudflare_provider import CloudflareImageProvider
from ai_content_agent.providers.image.exceptions import ImageProviderError
from ai_content_agent.providers.image.pillow_provider import PillowImageProvider
from ai_content_agent.settings import load_settings


def jpeg_bytes(size=(64, 64)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (20, 90, 160)).save(buffer, "JPEG")
    return buffer.getvalue()


def request(**extra) -> ImageRequest:
    return ImageRequest(prompt="lone swordsman under an eclipse, cinematic", brand_style="clean", aspect_ratio="1:1", **extra)


def reply(status=200, body=None, text=""):
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    if body is None:
        resp.json.side_effect = ValueError("not json")
    else:
        resp.json.return_value = body
    return resp


class InTempDir(unittest.TestCase):
    def setUp(self):
        self._cwd = os.getcwd()
        self.tmp = tempfile.TemporaryDirectory()
        os.chdir(self.tmp.name)

    def tearDown(self):
        os.chdir(self._cwd)
        self.tmp.cleanup()


class CloudflareProviderTests(InTempDir):
    def provider(self, session, **kwargs):
        return CloudflareImageProvider(account_id="acc1", api_token="SECRET-TOKEN", session=session, **kwargs)

    def test_request_shape_and_saved_image(self):
        session = MagicMock()
        session.post.return_value = reply(body={"image": base64.b64encode(jpeg_bytes((1024, 1024))).decode()})
        result = self.provider(session).generate(request())
        url = session.post.call_args.args[0]
        kwargs = session.post.call_args.kwargs
        self.assertEqual(url, "https://api.cloudflare.com/client/v4/accounts/acc1/ai/run/@cf/black-forest-labs/flux-1-schnell")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer SECRET-TOKEN")
        self.assertEqual(kwargs["json"]["steps"], 4)
        self.assertIn("no text", kwargs["json"]["prompt"])  # FLUX draws letters badly
        self.assertEqual((result.provider, result.metadata["dimensions"], result.metadata["watermark"]), ("cloudflare", "1024x1024", False))
        self.assertTrue(Path(result.file_path).exists())

    def test_wrapped_result_shape_is_accepted_too(self):
        session = MagicMock()
        session.post.return_value = reply(body={"result": {"image": base64.b64encode(jpeg_bytes()).decode()}, "success": True})
        self.assertEqual(self.provider(session).generate(request()).provider, "cloudflare")

    def test_prompt_is_capped_at_the_documented_limit(self):
        session = MagicMock()
        session.post.return_value = reply(body={"image": base64.b64encode(jpeg_bytes()).decode()})
        self.provider(session).generate(ImageRequest("x" * 5000, "clean", "1:1"))
        self.assertEqual(len(session.post.call_args.kwargs["json"]["prompt"]), 2048)

    def test_unconfigured_provider_refuses_without_a_request(self):
        session = MagicMock()
        provider = CloudflareImageProvider(account_id=None, api_token=None, session=session)
        with patch.object(CloudflareImageProvider, "_settings", return_value=None):
            provider = CloudflareImageProvider(account_id=None, api_token=None, session=session)
        self.assertFalse(provider.configured)
        with self.assertRaises(ImageProviderError):
            provider.generate(request())
        session.post.assert_not_called()

    def test_bad_token_is_not_retried_and_never_leaks(self):
        session = MagicMock()
        session.post.return_value = reply(status=401, text="invalid token SECRET-TOKEN")
        with self.assertRaises(ImageProviderError) as ctx:
            self.provider(session, max_attempts=3).generate(request())
        self.assertEqual(session.post.call_count, 1)
        self.assertNotIn("SECRET-TOKEN", str(ctx.exception))

    @patch("ai_content_agent.providers.image.cloudflare_provider.time.sleep")
    def test_server_errors_are_retried(self, sleep):
        session = MagicMock()
        session.post.side_effect = [reply(status=503, text="busy"), reply(body={"image": base64.b64encode(jpeg_bytes()).decode()})]
        self.assertEqual(self.provider(session).generate(request()).provider, "cloudflare")
        self.assertEqual(session.post.call_count, 2)

    @patch("ai_content_agent.providers.image.cloudflare_provider.time.sleep")
    def test_network_errors_and_garbage_are_failures(self, sleep):
        session = MagicMock()
        session.post.side_effect = requests.ConnectionError("down SECRET-TOKEN")
        with self.assertRaises(ImageProviderError) as ctx:
            self.provider(session).generate(request())
        self.assertNotIn("SECRET-TOKEN", str(ctx.exception))
        session.post.side_effect = None
        session.post.return_value = reply(body={"image": base64.b64encode(b"not an image").decode()})
        with self.assertRaises(ImageProviderError):
            self.provider(session).generate(request())
        session.post.return_value = reply(body={"unexpected": 1})
        with self.assertRaises(ImageProviderError):
            self.provider(session).generate(request())


class AutoProviderTests(InTempDir):
    def test_uses_the_first_configured_working_provider(self):
        cloudflare = MagicMock()
        cloudflare.configured = True
        cloudflare.generate.return_value = MagicMock(provider="cloudflare", prompt="p", file_path="a.jpg", metadata={"x": 1})
        with patch("ai_content_agent.providers.image.cloudflare_provider.CloudflareImageProvider", return_value=cloudflare):
            result = AutoImageProvider(chain=("cloudflare", "pillow")).generate(request())
        self.assertEqual((result.provider, result.metadata["chain_tried"]), ("cloudflare", []))

    def test_unconfigured_providers_are_skipped_and_the_next_one_used(self):
        unconfigured = MagicMock()
        unconfigured.configured = False
        pollinations = MagicMock()
        pollinations.generate.return_value = MagicMock(provider="pollinations", prompt="p", file_path="b.jpg", metadata={})
        with patch("ai_content_agent.providers.image.cloudflare_provider.CloudflareImageProvider", return_value=unconfigured), patch(
            "ai_content_agent.providers.image.pollinations_provider.PollinationsImageProvider", return_value=pollinations
        ) as factory:
            result = AutoImageProvider(chain=("cloudflare", "pollinations", "pillow")).generate(request())
        self.assertEqual(result.provider, "pollinations")
        self.assertEqual(result.metadata["chain_tried"], ["cloudflare: not configured"])
        factory.assert_called_once_with(fallback_to_pillow=False)  # the chain, not Pollinations, picks the fallback

    def test_a_failing_provider_falls_through_to_the_offline_poster(self):
        failing = MagicMock()
        failing.generate.side_effect = ImageProviderError("HTTP 503 busy")
        with patch("ai_content_agent.providers.image.pollinations_provider.PollinationsImageProvider", return_value=failing):
            result = AutoImageProvider(chain=("pollinations", "pillow")).generate(request(headline="Quiet craft beats loud talent."))
        self.assertEqual(result.provider, "pillow")
        self.assertTrue(Path(result.file_path).exists())
        self.assertIn("503", result.metadata["chain_tried"][0])

    def test_all_failing_raises_with_every_reason(self):
        failing = MagicMock()
        failing.generate.side_effect = ImageProviderError("nope")
        with patch("ai_content_agent.providers.image.pollinations_provider.PollinationsImageProvider", return_value=failing):
            with self.assertRaises(ImageProviderError) as ctx:
                AutoImageProvider(chain=("pollinations",)).generate(request())
        self.assertIn("pollinations: nope", str(ctx.exception))

    def test_default_chain_and_validation(self):
        env = {"LOG_LEVEL": "INFO", "DATABASE_PATH": ":memory:", "OPENCODE_COMMAND": "o", "INSTAGRAM_ENABLED": "false", "IMAGE_PROVIDER": "auto"}
        self.assertEqual(load_settings(env=env, env_file=Path("none.env")).image_chain, ("cloudflare", "pollinations", "pillow"))
        custom = load_settings(env={**env, "IMAGE_CHAIN": " Pillow , cloudflare"}, env_file=Path("none.env"))
        self.assertEqual(custom.image_chain, ("pillow", "cloudflare"))
        with self.assertRaises(ValueError):
            AutoImageProvider(chain=("pillow",)).validate(ImageRequest("", "clean", "1:1"))


class PillowPosterTests(InTempDir):
    def test_the_poster_uses_the_posts_own_headline(self):
        provider = PillowImageProvider()
        _, _, _, quote = provider._resolve_copy("anime art", True, "Quiet craft beats loud talent.")
        self.assertEqual(quote, '"Quiet craft beats loud talent."')
        _, _, _, fixed = provider._resolve_copy("anime art", True, "")
        self.assertIn("final blow", fixed)  # the old fixed text is only the no-headline fallback

    def test_different_headlines_get_different_title_blocks_and_the_same_one_is_stable(self):
        provider = PillowImageProvider()
        titles = {provider._resolve_copy("p", True, f"Headline number {i} about discipline")[1] for i in range(40)}
        self.assertGreater(len(titles), 2)
        self.assertEqual(provider._resolve_copy("p", True, "Same")[1], provider._resolve_copy("p", True, "Same")[1])

    def test_long_text_is_never_cut_mid_sentence_without_an_ellipsis(self):
        text = "They never see the ten thousand hours in the shadows, " * 6
        lines = PillowPosterTests.provider_lines(text)
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[-1].endswith("…"))
        self.assertTrue(all(len(line) <= 46 for line in lines))

    def test_short_text_is_untouched(self):
        self.assertEqual(PillowPosterTests.provider_lines("A short line."), ["A short line."])

    @staticmethod
    def provider_lines(text):
        return PillowImageProvider._fit_lines(text, max_chars=46, max_lines=3)

    def test_a_full_poster_renders_with_a_headline(self):
        result = PillowImageProvider().generate(request(headline="Ever wondered why the silent hours matter more than the loud ones?"))
        with Image.open(result.file_path) as image:
            self.assertEqual(image.size, (1080, 1080))


if __name__ == "__main__":
    unittest.main()
