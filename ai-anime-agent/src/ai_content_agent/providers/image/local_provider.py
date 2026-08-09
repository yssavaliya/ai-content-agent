from __future__ import annotations

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
        file_path = output_dir / f"image_prompt_{now.strftime('%H%M%S')}.txt"
        created_at = format_utc(now)
        content = (
            f"IMAGE PROMPT\n"
            f"===========\n"
            f"{request.prompt}\n\n"
            f"BRAND STYLE\n"
            f"===========\n"
            f"{request.brand_style}\n\n"
            f"ASPECT RATIO: {request.aspect_ratio}\n"
            f"CREATED AT (UTC): {created_at}\n"
        )
        file_path.write_text(content, encoding="utf-8")
        return ImageResult(
            provider=self.name,
            prompt=request.prompt,
            file_path=str(file_path),
            metadata={"created_at": created_at, "provider": self.name},
        )
