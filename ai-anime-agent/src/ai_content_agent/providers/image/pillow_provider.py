from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ...timestamps import format_utc, utc_now
from .base import BaseImageProvider, ImageRequest, ImageResult
from .exceptions import ImageProviderError
from .registry import ImageProviderRegistry

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None
    ImageDraw = None
    ImageFont = None

logger = logging.getLogger(__name__)


@ImageProviderRegistry.register
class PillowImageProvider(BaseImageProvider):
    """Generates genuine, high-resolution visual PNG graphics using Pillow."""

    name = "pillow"

    _DIMENSIONS = {
        "1:1": (1080, 1080),
        "4:5": (1080, 1350),
        "16:9": (1920, 1080),
    }

    def validate(self, request: ImageRequest) -> None:
        if not request.prompt.strip():
            raise ValueError("Image prompt must not be empty")
        if request.aspect_ratio not in self._DIMENSIONS:
            raise ValueError(f"Unsupported aspect ratio: {request.aspect_ratio}")

    def generate(self, request: ImageRequest) -> ImageResult:
        self.validate(request)
        if Image is None or ImageDraw is None:
            raise ImageProviderError("Pillow is required for pillow image provider; run: pip install Pillow")

        width, height = self._DIMENSIONS[request.aspect_ratio]
        image = self._create_artwork(width, height, request.prompt, request.brand_style)

        now = utc_now()
        output_dir = Path("images") / now.strftime("%Y") / now.strftime("%m") / now.strftime("%d")
        output_dir.mkdir(parents=True, exist_ok=True)
        file_path = output_dir / f"pillow_image_{now.strftime('%H%M%S_%f')[:17]}.png"

        image.save(file_path, "PNG", optimize=True)
        created_at = format_utc(now)

        metadata: dict[str, Any] = {
            "provider": self.name,
            "dimensions": f"{width}x{height}",
            "width": width,
            "height": height,
            "aspect_ratio": request.aspect_ratio,
            "format": "PNG",
            "created_at": created_at,
        }

        logger.info("Generated genuine image %s (%dx%d, %s)", file_path, width, height, request.aspect_ratio)
        return ImageResult(
            provider=self.name,
            prompt=request.prompt,
            file_path=str(file_path),
            metadata=metadata,
        )

    def _create_artwork(self, width: int, height: int, prompt: str, brand_style: str) -> Any:
        img = Image.new("RGB", (width, height), color=(15, 17, 26))
        draw = ImageDraw.Draw(img)

        # Draw smooth vertical cyber/anime gradient (Deep Navy #0d111a to Anime Purple #2b1055 to Magenta #591a75)
        for y in range(height):
            ratio = y / height
            if ratio < 0.5:
                sub_r = ratio / 0.5
                r = int(13 + (43 - 13) * sub_r)
                g = int(17 + (16 - 17) * sub_r)
                b = int(26 + (85 - 26) * sub_r)
            else:
                sub_r = (ratio - 0.5) / 0.5
                r = int(43 + (89 - 43) * sub_r)
                g = int(16 + (26 - 16) * sub_r)
                b = int(85 + (117 - 85) * sub_r)
            draw.line([(0, y), (width, y)], fill=(r, g, b))

        # Stylized background grid / diagonal accent lines
        for i in range(-height, width, 120):
            draw.line([(i, 0), (i + height, height)], fill=(40, 50, 90), width=1)


        # Draw glowing inner card border
        margin = int(width * 0.05)
        draw.rectangle(
            [(margin, margin), (width - margin, height - margin)],
            outline=(255, 42, 133),
            width=3,
        )
        draw.rectangle(
            [(margin + 6, margin + 6), (width - margin - 6, height - margin - 6)],
            outline=(0, 242, 254),
            width=1,
        )

        # Header Badge
        badge_text = "ANIME AI INDIA  •  CONCEPT KEY VISUAL"
        draw.rectangle(
            [(margin + 20, margin + 20), (margin + 420, margin + 65)],
            fill=(255, 42, 133),
        )
        draw.text((margin + 35, margin + 32), badge_text, fill=(255, 255, 255))

        # Extract title from prompt if possible
        title = "ORIGINAL ANIME VISUAL"
        for candidate in ["for '", 'for "', "visual for "]:
            if candidate in prompt:
                part = prompt.split(candidate, 1)[1]
                title = part.split("'", 1)[0].split('"', 1)[0].split(",", 1)[0].strip()
                break

        # Render Main Title
        draw.text((margin + 25, margin + 100), title.upper()[:40], fill=(255, 255, 255))
        draw.line([(margin + 25, margin + 140), (margin + 350, margin + 140)], fill=(0, 242, 254), width=3)

        # Render wrapped prompt snippet
        prompt_snippet = prompt.replace("\n", " ")
        lines = self._wrap_text(prompt_snippet, max_chars=int(width * 0.045))[:8]
        curr_y = margin + 170
        for line in lines:
            draw.text((margin + 25, curr_y), line, fill=(220, 225, 240))
            curr_y += 32

        # Footer watermark
        footer_y = height - margin - 50
        draw.line([(margin + 20, footer_y), (width - margin - 20, footer_y)], fill=(80, 90, 120), width=1)
        draw.text((margin + 25, footer_y + 15), f"STYLE: {brand_style.upper()}  |  ASPECT: {int(width)}x{int(height)}", fill=(160, 175, 200))
        draw.text((width - margin - 220, footer_y + 15), "@ANIME_AI_INDIA", fill=(0, 242, 254))

        return img

    @staticmethod
    def _wrap_text(text: str, max_chars: int) -> list[str]:
        words = text.split()
        lines: list[str] = []
        current = ""
        for word in words:
            if len(current) + len(word) + 1 <= max_chars:
                current = f"{current} {word}".strip()
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines
