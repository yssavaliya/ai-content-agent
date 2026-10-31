from __future__ import annotations

import logging
import random
import urllib.parse
from pathlib import Path

import requests

from ...timestamps import format_utc, utc_now
from .base import BaseImageProvider, ImageRequest, ImageResult
from .exceptions import ImageProviderError
from .pillow_provider import PillowImageProvider
from .registry import ImageProviderRegistry

logger = logging.getLogger(__name__)

POLLINATIONS_API_BASE = "https://image.pollinations.ai/prompt"


@ImageProviderRegistry.register
class PollinationsImageProvider(BaseImageProvider):
    """Generates authentic, state-of-the-art AI images via FLUX.1 on Pollinations AI.

    Requires no API keys. Yields hyper-cinematic 1080x1080 visual art.
    Automatically falls back to PillowImageProvider if offline or timed out.
    """

    name = "pollinations"

    _DIMENSIONS = {
        "1:1": (1080, 1080),
        "4:5": (1080, 1350),
        "16:9": (1920, 1080),
    }

    def __init__(
        self,
        model: str = "flux",
        timeout_seconds: int = 45,
        fallback_to_pillow: bool = True,
    ) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.fallback_to_pillow = fallback_to_pillow

    def validate(self, request: ImageRequest) -> None:
        if not request.prompt or not request.prompt.strip():
            raise ValueError("Image prompt must not be empty")
        if request.aspect_ratio not in self._DIMENSIONS:
            raise ValueError(
                f"Unsupported aspect ratio: {request.aspect_ratio!r} (supported: {list(self._DIMENSIONS)})"
            )

    def _enhance_prompt(self, prompt: str) -> str:
        """Enrich prompt with cinematic and aesthetic keywords for viral Instagram impact."""
        aesthetic_tags = (
            "masterpiece, cinematic lighting, 8k resolution, volumetric atmospheric glow, "
            "detailed anime concept art, trending on artstation, octane render, sharp focus"
        )
        if any(tag in prompt.lower() for tag in ["masterpiece", "cinematic", "octane", "8k"]):
            return prompt
        return f"{prompt}, {aesthetic_tags}"

    def generate(self, request: ImageRequest) -> ImageResult:
        self.validate(request)
        width, height = self._DIMENSIONS[request.aspect_ratio]
        enhanced_prompt = self._enhance_prompt(request.prompt)
        seed = random.randint(1, 99999999)

        encoded_prompt = urllib.parse.quote(enhanced_prompt)
        url = (
            f"{POLLINATIONS_API_BASE}/{encoded_prompt}"
            f"?width={width}&height={height}&model={self.model}&nologo=true&seed={seed}"
        )

        logger.info(
            "Requesting FLUX AI image from Pollinations (model=%s, size=%sx%s)",
            self.model,
            width,
            height,
        )

        try:
            resp = requests.get(url, timeout=self.timeout_seconds)
            if resp.status_code == 200 and resp.content:
                # Determine output path
                now = utc_now()
                rel_dir = Path("images") / now.strftime("%Y") / now.strftime("%m") / now.strftime("%d")
                rel_dir.mkdir(parents=True, exist_ok=True)
                filename = f"flux_image_{now.strftime('%H%M%S')}_{seed % 1000000:06d}.jpg"
                file_path = rel_dir / filename
                file_path.write_bytes(resp.content)

                logger.info("Saved FLUX AI image (%s bytes) to %s", len(resp.content), file_path)
                return ImageResult(
                    provider=self.name,
                    prompt=request.prompt,
                    file_path=str(file_path).replace("\\", "/"),
                    metadata={
                        "provider": self.name,
                        "model": self.model,
                        "width": width,
                        "height": height,
                        "dimensions": f"{width}x{height}",
                        "aspect_ratio": request.aspect_ratio,
                        "format": "JPEG",
                        "seed": seed,
                        "enhanced_prompt": enhanced_prompt,
                        "created_at": format_utc(now),
                    },
                )
            logger.warning("Pollinations API returned status %s: %s", resp.status_code, resp.text[:200])
        except Exception as exc:
            logger.warning("Pollinations image generation failed: %s", exc)

        if not self.fallback_to_pillow:
            raise ImageProviderError(f"Pollinations generation failed for prompt: {request.prompt[:50]}")

        logger.info("Falling back to PillowImageProvider for safety...")
        pillow_provider = PillowImageProvider()
        return pillow_provider.generate(request)


@ImageProviderRegistry.register
class FluxImageProvider(PollinationsImageProvider):
    """Alias for PollinationsImageProvider with FLUX model."""

    name = "flux"

