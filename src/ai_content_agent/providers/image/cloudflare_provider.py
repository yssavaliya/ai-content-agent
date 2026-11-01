from __future__ import annotations

import base64
import binascii
import io
import logging
import time
from pathlib import Path
from typing import Any

import requests

from ...redaction import redact
from ...timestamps import format_utc, utc_now
from .base import BaseImageProvider, ImageRequest, ImageResult
from .exceptions import ImageProviderError
from .registry import ImageProviderRegistry

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "@cf/black-forest-labs/flux-1-schnell"
API_BASE = "https://api.cloudflare.com/client/v4/accounts"
MAX_PROMPT_CHARS = 2048  # documented limit of flux-1-schnell
NO_TEXT_SUFFIX = ", no text, no watermark, no letters"


@ImageProviderRegistry.register
class CloudflareImageProvider(BaseImageProvider):
    """FLUX.1 [schnell] on Cloudflare Workers AI: no watermark, 1024 px, inside the free daily allowance.

    Needs CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN (Workers AI permission), the same credentials the
    LLM chain uses. Request and response shapes follow Cloudflare's model page; the response is accepted both
    as ``{"image": ...}`` and wrapped as ``{"result": {"image": ...}}``.
    """

    name = "cloudflare"
    _ASPECTS = {"1:1", "4:5", "16:9"}

    def __init__(
        self,
        account_id: str | None = None,
        api_token: str | None = None,
        model: str | None = None,
        steps: int = 4,
        timeout_seconds: int = 90,
        max_attempts: int = 2,
        session: Any | None = None,
    ) -> None:
        settings = self._settings()
        self.account_id = account_id or (settings.cloudflare_account_id if settings else None)
        self.api_token = api_token or (settings.cloudflare_api_token if settings else None)
        self.model = model or (settings.cloudflare_image_model if settings else None) or DEFAULT_MODEL
        self.steps = steps
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max(1, max_attempts)
        self._session = session or requests

    @staticmethod
    def _settings() -> Any | None:
        try:
            from ...settings import current_settings

            return current_settings()
        except ValueError:
            return None

    @property
    def configured(self) -> bool:
        return bool(self.account_id and self.api_token)

    def validate(self, request: ImageRequest) -> None:
        if not request.prompt.strip():
            raise ValueError("Image prompt must not be empty")
        if request.aspect_ratio not in self._ASPECTS:
            raise ValueError(f"Unsupported aspect ratio: {request.aspect_ratio}")

    def _prompt(self, prompt: str) -> str:
        text = prompt.strip()
        if "no text" not in text.lower():
            text += NO_TEXT_SUFFIX
        return text[:MAX_PROMPT_CHARS]

    def generate(self, request: ImageRequest) -> ImageResult:
        self.validate(request)
        if not self.configured:
            raise ImageProviderError("CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN are required")

        url = f"{API_BASE}/{self.account_id}/ai/run/{self.model}"
        headers = {"Authorization": f"Bearer {self.api_token}", "Content-Type": "application/json"}
        body = {"prompt": self._prompt(request.prompt), "steps": self.steps}
        last_error = "no attempt made"
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self._session.post(url, headers=headers, json=body, timeout=self.timeout_seconds)
            except requests.RequestException as exc:
                last_error = f"network error: {redact(str(exc), self.api_token)[:160]}"
            else:
                if response.status_code == 200:
                    return self._save(request, self._decode(response))
                last_error = f"HTTP {response.status_code}: {redact(response.text or '', self.api_token)[:200]}"
                if response.status_code not in (408, 429) and response.status_code < 500:
                    break  # a bad token, model or prompt will not get better by retrying
            if attempt < self.max_attempts:
                time.sleep(3.0)
        raise ImageProviderError(f"Cloudflare image generation failed: {last_error}")

    @staticmethod
    def _decode(response: Any) -> bytes:
        try:
            data = response.json()
        except ValueError:
            raise ImageProviderError("Cloudflare returned a non-JSON response") from None
        payload = data.get("result", data) if isinstance(data, dict) else {}
        encoded = payload.get("image") if isinstance(payload, dict) else None
        if not isinstance(encoded, str) or not encoded:
            raise ImageProviderError("Cloudflare response contained no image")
        try:
            return base64.b64decode(encoded, validate=False)
        except (binascii.Error, ValueError):
            raise ImageProviderError("Cloudflare image was not valid base64") from None

    def _save(self, request: ImageRequest, data: bytes) -> ImageResult:
        try:
            from PIL import Image

            with Image.open(io.BytesIO(data)) as image:
                image.load()
                width, height = image.size
                fmt = image.format or "JPEG"
        except Exception as exc:  # noqa: BLE001 - any decode problem means "not an image"
            raise ImageProviderError(f"Cloudflare returned data that is not an image: {exc}") from None
        now = utc_now()
        folder = Path("images") / now.strftime("%Y") / now.strftime("%m") / now.strftime("%d")
        folder.mkdir(parents=True, exist_ok=True)
        extension = "png" if fmt.upper() == "PNG" else "jpg"
        path = folder / f"cloudflare_flux_{now.strftime('%H%M%S_%f')[:13]}.{extension}"
        path.write_bytes(data)
        logger.info("Saved Cloudflare FLUX image (%dx%d, %s bytes) to %s", width, height, len(data), path)
        return ImageResult(
            provider=self.name,
            prompt=request.prompt,
            file_path=str(path).replace("\\", "/"),
            metadata={
                "provider": self.name,
                "model": self.model,
                "steps": self.steps,
                "width": width,
                "height": height,
                "dimensions": f"{width}x{height}",
                "format": fmt,
                "watermark": False,
                "created_at": format_utc(now),
            },
        )
