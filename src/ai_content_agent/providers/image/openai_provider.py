from __future__ import annotations

import base64
import logging
import time
from pathlib import Path
from typing import Any

from ...timestamps import utc_now
from .base import BaseImageProvider, ImageRequest, ImageResult
from .exceptions import ImageProviderError
from .registry import ImageProviderRegistry

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

logger = logging.getLogger(__name__)


@ImageProviderRegistry.register
class OpenAIImageProvider(BaseImageProvider):
    name = "openai"
    model = "gpt-image-1"

    _SIZES = {
        "1:1": "1024x1024",
        "4:5": "1024x1280",
        "16:9": "1536x1024",
    }

    def __init__(
        self,
        api_key: str | None = None,
        client: Any | None = None,
        model: str | None = None,
        max_retries: int | None = None,
        request_timeout_seconds: int | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.max_retries = max_retries
        self.request_timeout_seconds = request_timeout_seconds
        self._client = client
        self._settings: Any | None = None

    def _resolve_settings(self) -> Any | None:
        if self._settings is not None:
            return self._settings
        try:
            from ...settings import current_settings

            self._settings = current_settings()
        except ValueError:
            self._settings = None
        return self._settings

    def validate(self, request: ImageRequest) -> None:
        if not request.prompt.strip():
            raise ValueError("Image prompt must not be empty")
        if request.aspect_ratio not in self._SIZES:
            raise ValueError("Unsupported aspect ratio")

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if OpenAI is None:
            raise ImageProviderError(
                "The 'openai' package is required for the openai image provider; run: pip install openai"
            )
        settings = self._resolve_settings()
        api_key = self.api_key or (settings.openai_api_key if settings else None)
        if not api_key:
            raise ImageProviderError("OPENAI_API_KEY is required for the openai image provider")
        timeout = self.request_timeout_seconds
        if timeout is None:
            timeout = settings.openai_request_timeout_seconds if settings else 60
        max_retries = self.max_retries
        if max_retries is None:
            max_retries = settings.openai_max_retries if settings else 3
        return OpenAI(
            api_key=api_key,
            timeout=timeout,
            max_retries=max_retries,
        )

    def generate(self, request: ImageRequest) -> ImageResult:
        self.validate(request)
        size = self._SIZES[request.aspect_ratio]
        model = self.model
        if model is None:
            settings = self._resolve_settings()
            model = (settings.openai_model if settings else None) or "gpt-image-1"
        client = self._get_client()

        max_retries = self.max_retries
        if max_retries is None:
            settings = self._resolve_settings()
            max_retries = settings.openai_max_retries if settings else 3
        if max_retries < 1:
            raise ImageProviderError("max_retries must be at least 1")

        for attempt in range(1, max_retries + 1):
            try:
                response = client.images.generate(model=model, prompt=request.prompt, size=size)
                break
            except Exception as exc:
                if attempt >= max_retries:
                    logger.error("OpenAI image generation failed after %s attempts: %s", attempt, exc)
                    raise ImageProviderError(f"OpenAI image generation failed: {exc}") from exc
                backoff = 2 ** attempt
                logger.warning(
                    "OpenAI image generation attempt %s/%s failed (%s); retrying in %ss",
                    attempt,
                    max_retries,
                    exc,
                    backoff,
                )
                time.sleep(backoff)

        if not response.data:
            raise ImageProviderError("OpenAI returned no image data")
        image_data = response.data[0]
        encoded = getattr(image_data, "b64_json", None)
        if not encoded:
            raise ImageProviderError("OpenAI returned no base64 image data")

        now = utc_now()
        output_dir = Path("images") / now.strftime("%Y") / now.strftime("%m") / now.strftime("%d")
        output_dir.mkdir(parents=True, exist_ok=True)
        file_path = output_dir / f"openai_image_{now.strftime('%H%M%S')}.png"
        file_path.write_bytes(base64.b64decode(encoded))

        logger.info("Generated image %s (model=%s, size=%s)", file_path, self.model, size)
        return ImageResult(
            provider=self.name,
            prompt=request.prompt,
            file_path=str(file_path),
            metadata={
                "model": model,
                "size": size,
                "created_at": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
                "revised_prompt": getattr(image_data, "revised_prompt", None),
            },
        )
