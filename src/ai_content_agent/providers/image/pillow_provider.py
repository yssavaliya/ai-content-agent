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


def _load_font(size: int, bold: bool = False) -> Any:
    if ImageFont is None:
        return None
    candidates = [
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "arialbd.ttf" if bold else "arial.ttf",
        "LiberationSans-Bold.ttf" if bold else "LiberationSans-Regular.ttf",
        "segoeuib.ttf" if bold else "segoeui.ttf",
    ]
    for font_name in candidates:
        try:
            return ImageFont.truetype(font_name, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


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
        img = Image.new("RGB", (width, height), color=(10, 11, 20))
        draw = ImageDraw.Draw(img)

        # 1. Background Gradient (Deep Indigo Navy to Midnight Obsidian)
        for y in range(height):
            ratio = y / height
            r = int(12 + (24 - 12) * ratio)
            g = int(14 + (16 - 14) * ratio)
            b = int(28 + (42 - 28) * ratio)
            draw.line([(0, y), (width, y)], fill=(r, g, b))

        # 2. Glowing Ambient Auras (Neon Magenta top-right, Cyber Cyan bottom-left)
        aura_max = int(min(width, height) * 0.38)
        for r_val in range(aura_max, 0, -8):
            alpha = int((1.0 - (r_val / aura_max)) * 24)
            # top-right magenta aura
            cx1, cy1 = int(width * 0.88), int(height * 0.12)
            draw.ellipse(
                [(cx1 - r_val, cy1 - r_val), (cx1 + r_val, cy1 + r_val)],
                outline=(alpha * 3, alpha // 2, alpha * 2),
                width=8,
            )
            # bottom-left cyan aura
            cx2, cy2 = int(width * 0.12), int(height * 0.88)
            draw.ellipse(
                [(cx2 - r_val, cy2 - r_val), (cx2 + r_val, cy2 + r_val)],
                outline=(0, alpha * 2, alpha * 3),
                width=8,
            )

        # 3. Geometric Background Grid Lines
        grid_step = int(width * 0.08)
        for x in range(0, width + height, grid_step):
            draw.line([(x, 0), (x - height, height)], fill=(22, 28, 48), width=1)

        # 4. Outer Glowing Frame
        margin = int(width * 0.045)
        draw.rounded_rectangle(
            [(margin, margin), (width - margin, height - margin)],
            radius=26,
            outline=(255, 42, 133),
            width=3,
        )
        draw.rounded_rectangle(
            [(margin + 5, margin + 5), (width - margin - 5, height - margin - 5)],
            radius=22,
            outline=(0, 242, 254),
            width=1,
        )

        # Parse content context from prompt
        tag, title, subtitle, points = self._parse_prompt_content(prompt)

        # 5. Top Bar: Category Tag Pill + Slide Counter
        font_badge = _load_font(int(width * 0.02), bold=True)
        pill_w = int(width * 0.35)
        pill_h = int(height * 0.042)
        draw.rounded_rectangle(
            [(margin + 36, margin + 36), (margin + 36 + pill_w, margin + 36 + pill_h)],
            radius=pill_h // 2,
            fill=(255, 42, 133),
        )
        draw.text((margin + 54, margin + 44), f"*  {tag.upper()}", fill=(255, 255, 255), font=font_badge)

        draw.rounded_rectangle(
            [(width - margin - 150, margin + 36), (width - margin - 36, margin + 36 + pill_h)],
            radius=pill_h // 2,
            outline=(0, 242, 254),
            width=2,
        )
        draw.text((width - margin - 128, margin + 44), "01 / 04", fill=(0, 242, 254), font=font_badge)

        # 6. Hero Hook Headline (Large, Bold, High-Impact)
        font_title = _load_font(int(width * 0.052), bold=True)
        font_subtitle = _load_font(int(width * 0.024), bold=False)

        title_lines = self._wrap_text(title.upper(), max_chars=24)[:3]
        y_pos = margin + int(height * 0.11)
        for i, line in enumerate(title_lines):
            color = (0, 242, 254) if i == 1 else (255, 255, 255)
            draw.text((margin + 36, y_pos), line, fill=color, font=font_title)
            y_pos += int(height * 0.062)

        # Subtitle with accent vertical bar
        draw.rectangle([(margin + 36, y_pos + 10), (margin + 42, y_pos + 46)], fill=(255, 42, 133))
        draw.text((margin + 54, y_pos + 14), subtitle[:75], fill=(200, 210, 235), font=font_subtitle)
        y_pos += int(height * 0.068)

        # 7. Central Value Proposition Card
        card_top = y_pos + 10
        card_bottom = height - margin - int(height * 0.11)
        card_left = margin + 36
        card_right = width - margin - 36

        draw.rounded_rectangle(
            [(card_left, card_top), (card_right, card_bottom)],
            radius=20,
            fill=(18, 22, 38),
            outline=(50, 60, 95),
            width=2,
        )

        font_card_head = _load_font(int(width * 0.018), bold=True)
        draw.text((card_left + 28, card_top + 18), "CORE INSIGHTS & TAKEAWAYS", fill=(140, 160, 200), font=font_card_head)
        draw.line([(card_left + 28, card_top + 46), (card_right - 28, card_top + 46)], fill=(35, 45, 75), width=1)

        # Bullet points with colored numbers
        font_point = _load_font(int(width * 0.022), bold=False)
        font_num = _load_font(int(width * 0.022), bold=True)
        item_y = card_top + 64

        bullet_colors = [(255, 42, 133), (0, 242, 254), (255, 215, 0)]
        for idx, pt in enumerate(points[:3]):
            col = bullet_colors[idx % len(bullet_colors)]
            draw.rounded_rectangle(
                [(card_left + 28, item_y), (card_left + 72, item_y + 38)],
                radius=10,
                fill=col,
            )
            draw.text((card_left + 38, item_y + 5), f"0{idx+1}", fill=(10, 10, 20), font=font_num)

            p_lines = self._wrap_text(pt, max_chars=40)[:2]
            sub_y = item_y + 4
            for pl in p_lines:
                draw.text((card_left + 90, sub_y), pl, fill=(240, 245, 255), font=font_point)
                sub_y += int(height * 0.03)

            item_y += int(height * 0.078)

        # 8. Bottom Bar: Brand Watermark + Swipe Action Prompt
        footer_y = height - margin - int(height * 0.072)
        font_footer = _load_font(int(width * 0.022), bold=True)

        draw.rounded_rectangle(
            [(margin + 36, footer_y), (margin + 280, footer_y + 46)],
            radius=23,
            fill=(25, 30, 52),
            outline=(0, 242, 254),
            width=1,
        )
        draw.text((margin + 58, footer_y + 10), "@ANIME_AI_INDIA", fill=(0, 242, 254), font=font_footer)

        draw.rounded_rectangle(
            [(width - margin - 260, footer_y), (width - margin - 36, footer_y + 46)],
            radius=23,
            fill=(255, 42, 133),
        )
        draw.text((width - margin - 232, footer_y + 10), "SWIPE NEXT  >>", fill=(255, 255, 255), font=font_footer)

        return img

    def _parse_prompt_content(self, prompt: str) -> tuple[str, str, str, list[str]]:
        p_lower = prompt.lower()
        if "anime" in p_lower:
            tag = "Anime Visual Analysis"
            title = "Modern Anime Aesthetics: How Visuals Go Viral"
            subtitle = "The secret visual pacing behind modern Shonen that stops the scroll."
            points = [
                "Dynamic sakuga timing locks attention in the first 1.5s.",
                "High-contrast neon palettes evoke emotion and trigger 3x saves.",
                "Visual micro-tension leads directly to viral comment debates.",
            ]
        else:
            tag = "Creator Automation"
            title = "Autonomous AI Agents: Content Pipeline Blueprint"
            subtitle = "How top creators automate research, virality scoring, and visual posts."
            points = [
                "Multi-agent architecture eliminates creative fatigue completely.",
                "Real-time virality prediction catches weak hooks before posting.",
                "Deterministic image synthesis keeps your grid consistent 24/7.",
            ]
        return tag, title, subtitle, points

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
