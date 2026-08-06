from __future__ import annotations

import json
from pathlib import Path

from ...timestamps import format_utc, utc_now
from .base import BaseImageProvider, ImageRequest, ImageResult
from .registry import ImageProviderRegistry


@ImageProviderRegistry.register
class LocalImageProvider(BaseImageProvider):
    name = "local"

    def validate(self, request: ImageRequest) -> None:
        if not request.prompt.strip():
            raise ValueError("Image prompt must not be empty")
        if request.aspect_ratio not in {"1:1", "4:5", "16:9"}:
            raise ValueError("Unsupported aspect ratio")

    def generate(self, request: ImageRequest) -> ImageResult:
        self.validate(request)
        now = utc_now()
        output_dir = Path("images") / now.strftime("%Y") / now.strftime("%m") / now.strftime("%d")
        output_dir.mkdir(parents=True, exist_ok=True)
        file_path = output_dir / f"local_image_{now.strftime('%H%M%S')}.json"
        created_at = format_utc(now)
        payload = {
            "prompt": request.prompt,
            "brand_style": request.brand_style,
            "aspect_ratio": request.aspect_ratio,
            "created_at": created_at,
        }
        file_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return ImageResult(
            provider=self.name,
            prompt=request.prompt,
            file_path=str(file_path),
            metadata={"created_at": created_at, "provider": self.name},
        )
