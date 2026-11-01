from __future__ import annotations

import logging
import random
import re
import time
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
_RETRY_HINT = re.compile(r"retry after\s+(\d+(?:\.\d+)?)\s*s", flags=re.I)
MAX_RETRY_WAIT_SECONDS = 30.0
DEFAULT_RETRY_WAIT_SECONDS = 5.0


def _retry_wait(resp: "requests.Response | None") -> float:
    """Seconds to wait before retrying: Retry-After header, 'Retry after 10s' in the body, else a default."""
    if resp is not None:
        header = resp.headers.get("Retry-After") if hasattr(resp.headers, "get") else None
        try:
            if header:
                return min(max(float(header), 0.0), MAX_RETRY_WAIT_SECONDS)
        except (TypeError, ValueError):
            pass
        match = _RETRY_HINT.search(str(getattr(resp, "text", "") or ""))
        if match:
            return min(float(match.group(1)), MAX_RETRY_WAIT_SECONDS)
    return DEFAULT_RETRY_WAIT_SECONDS


def _retryable(resp: "requests.Response | None") -> bool:
    """A network error (no response), a rate limit (402/429) or a server error is worth another try."""
    return resp is None or resp.status_code in (402, 429) or resp.status_code >= 500


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
        max_attempts: int = 3,
    ) -> None:
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.fallback_to_pillow = fallback_to_pillow
        self.max_attempts = max(1, max_attempts)

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

        for attempt in range(1, self.max_attempts + 1):
            resp = None
            try:
                resp = requests.get(url, timeout=self.timeout_seconds)
            except Exception as exc:
                logger.warning("Pollinations image request failed (attempt %s/%s): %s", attempt, self.max_attempts, exc)
            if resp is not None and resp.status_code == 200 and resp.content:
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
            if resp is not None:
                logger.warning(
                    "Pollinations API returned status %s (attempt %s/%s): %s",
                    resp.status_code,
                    attempt,
                    self.max_attempts,
                    resp.text[:200],
                )
            if attempt < self.max_attempts and _retryable(resp):
                wait = _retry_wait(resp)
                logger.info("Retrying the Pollinations image in %.0fs", wait)
                time.sleep(wait)
                continue
            break

        if not self.fallback_to_pillow:
            raise ImageProviderError(f"Pollinations generation failed for prompt: {request.prompt[:50]}")

        logger.info("Falling back to PillowImageProvider for safety...")
        pillow_provider = PillowImageProvider()
        return pillow_provider.generate(request)


@ImageProviderRegistry.register
class FluxImageProvider(PollinationsImageProvider):
    """Alias for PollinationsImageProvider with FLUX model."""

    name = "flux"

