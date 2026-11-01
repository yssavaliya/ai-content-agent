from __future__ import annotations

import logging
from typing import Any

from .base import BaseImageProvider, ImageRequest, ImageResult
from .exceptions import ImageProviderError
from .registry import ImageProviderRegistry

logger = logging.getLogger(__name__)

DEFAULT_CHAIN = ("cloudflare", "pollinations", "pillow")


@ImageProviderRegistry.register
class AutoImageProvider(BaseImageProvider):
    """Tries image providers in IMAGE_CHAIN order and keeps the first that returns a real image.

    Default: Cloudflare FLUX.1 schnell (no watermark, needs the free Cloudflare credentials), then Pollinations
    FLUX (keyless, but adds its logo and is rate limited), then the offline Pillow poster, which cannot fail.
    A provider that is not configured is skipped without a request.
    """

    name = "auto"

    def __init__(self, chain: tuple[str, ...] | None = None) -> None:
        if chain is None:
            try:
                from ...settings import current_settings

                chain = current_settings().image_chain
            except ValueError:
                chain = DEFAULT_CHAIN
        self.chain = tuple(chain) or DEFAULT_CHAIN

    def validate(self, request: ImageRequest) -> None:
        if not request.prompt.strip():
            raise ValueError("Image prompt must not be empty")
        if request.aspect_ratio not in {"1:1", "4:5", "16:9"}:
            raise ValueError(f"Unsupported aspect ratio: {request.aspect_ratio}")

    @staticmethod
    def _build(name: str) -> BaseImageProvider | None:
        # Imported here: these modules register themselves with the registry on import.
        from .cloudflare_provider import CloudflareImageProvider
        from .pollinations_provider import PollinationsImageProvider

        if name == "cloudflare":
            provider = CloudflareImageProvider()
            return provider if provider.configured else None
        if name in ("pollinations", "flux"):
            # No internal fallback: the chain decides what comes next.
            return PollinationsImageProvider(fallback_to_pillow=False)
        return ImageProviderRegistry.get_provider(name)()

    def generate(self, request: ImageRequest) -> ImageResult:
        self.validate(request)
        tried: list[str] = []
        for name in self.chain:
            try:
                provider = self._build(name)
            except ImageProviderError as exc:
                tried.append(f"{name}: {exc}")
                continue
            if provider is None:
                tried.append(f"{name}: not configured")
                continue
            try:
                result = provider.generate(request)
            except Exception as exc:  # noqa: BLE001 - any failure means "try the next provider"
                logger.warning("Image provider %s failed: %s", name, exc)
                tried.append(f"{name}: {exc}")
                continue
            metadata: dict[str, Any] = {**result.metadata, "chain_tried": tried}
            return ImageResult(result.provider, result.prompt, result.file_path, metadata)
        raise ImageProviderError("All image providers failed: " + "; ".join(tried))
