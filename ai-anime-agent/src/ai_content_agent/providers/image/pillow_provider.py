from __future__ import annotations

import logging
import random
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
    """Generates genuine, high-impact cinematic visual artwork using Pillow."""

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
        img = Image.new("RGB", (width, height), color=(6, 7, 12))
        draw = ImageDraw.Draw(img)

        is_anime = "anime" in prompt.lower() or "shonen" in prompt.lower() or "blade" in prompt.lower()

        # 1. Background: Deep Celestial Obsidian with Cosmic Gradient
        for y in range(height):
            ratio = y / height
            if ratio < 0.6:
                sub = ratio / 0.6
                r = int(8 + (28 - 8) * sub)
                g = int(10 + (14 - 10) * sub)
                b = int(22 + (48 - 22) * sub)
            else:
                sub = (ratio - 0.6) / 0.4
                r = int(28 - (28 - 6) * sub)
                g = int(14 - (14 - 6) * sub)
                b = int(48 - (48 - 14) * sub)
            draw.line([(0, y), (width, y)], fill=(r, g, b))

        # 2. Celestial Glowing Eclipse / Moon in background (Center-Upper)
        moon_cx = width // 2
        moon_cy = int(height * 0.40)
        moon_r = int(min(width, height) * 0.20)

        # Outer Glow rings
        glow_steps = int(min(width, height) * 0.11)
        for glow in range(glow_steps, 0, -4):
            alpha = int((1.0 - (glow / float(glow_steps))) * 28)
            if is_anime:
                color = (alpha * 4, int(alpha * 0.8), int(alpha * 3.2))
            else:
                color = (0, int(alpha * 2.8), alpha * 4)
            draw.ellipse(
                [(moon_cx - moon_r - glow, moon_cy - moon_r - glow),
                 (moon_cx + moon_r + glow, moon_cy + moon_r + glow)],
                outline=color,
                width=4,
            )

        # Moon Sphere Body
        for mr in range(moon_r, 0, -2):
            frac = mr / float(moon_r)
            if is_anime:
                cr = int(255 - (255 - 180) * frac)
                cg = int(35 + (80 - 35) * frac)
                cb = int(90 + (160 - 90) * frac)
            else:
                cr = int(0 + (120 - 0) * frac)
                cg = int(242 - (242 - 160) * frac)
                cb = int(254 - (254 - 220) * frac)
            draw.ellipse(
                [(moon_cx - mr, moon_cy - mr), (moon_cx + mr, moon_cy + mr)],
                fill=(cr, cg, cb),
            )

        # Inner Dark Eclipse Shadow (Crescent overlay)
        shadow_offset = int(moon_r * 0.18)
        draw.ellipse(
            [(moon_cx - moon_r + shadow_offset, moon_cy - moon_r - 8),
             (moon_cx + moon_r + shadow_offset, moon_cy + moon_r - 8)],
            fill=(12, 10, 24),
        )

        # 3. Floating Stardust / Embers Particles
        rng = random.Random(42)
        for _ in range(85):
            px = rng.randint(20, width - 20)
            py = rng.randint(20, height - 20)
            psize = rng.choice([1, 2, 3, 4])
            if is_anime:
                pcol = rng.choice([
                    (255, 255, 255),
                    (0, 242, 254),
                    (255, 60, 140),
                    (180, 120, 255),
                    (255, 215, 120),
                ])
            else:
                pcol = rng.choice([
                    (255, 255, 255),
                    (0, 242, 254),
                    (57, 255, 20),
                    (0, 180, 255),
                    (255, 255, 255),
                ])
            draw.ellipse([(px, py), (px + psize, py + psize)], fill=pcol)

        # 4. Cinematic Silhouette: Mountain Ridge & Lone Hero Figure
        cliff_points = [
            (0, height),
            (0, int(height * 0.76)),
            (int(width * 0.35), int(height * 0.67)),
            (width // 2, int(height * 0.63)),
            (int(width * 0.65), int(height * 0.67)),
            (width, int(height * 0.76)),
            (width, height),
        ]
        draw.polygon(cliff_points, fill=(6, 6, 12))

        hx = width // 2
        hy = int(height * 0.63)
        # Cloak / Body
        draw.polygon(
            [(hx - 16, hy), (hx + 16, hy), (hx + 30, hy + 65), (hx - 30, hy + 65)],
            fill=(2, 2, 5),
        )
        # Head & Hair
        draw.ellipse([(hx - 10, hy - 26), (hx + 10, hy - 6)], fill=(2, 2, 5))
        draw.polygon([(hx - 14, hy - 22), (hx - 4, hy - 38), (hx + 6, hy - 24)], fill=(2, 2, 5))
        draw.polygon([(hx - 2, hy - 26), (hx + 12, hy - 40), (hx + 16, hy - 20)], fill=(2, 2, 5))

        # Glowing Katana Blade
        draw.line([(hx + 10, hy + 10), (hx + 75, hy + 50)], fill=(0, 242, 254), width=3)
        draw.line([(hx + 10, hy + 10), (hx + 75, hy + 50)], fill=(255, 255, 255), width=1)

        # 5. Glowing Energy Slash Beam across background
        slash_start = (int(width * 0.12), int(height * 0.46))
        slash_end = (int(width * 0.88), int(height * 0.30))
        slash_color = (0, 242, 254) if is_anime else (57, 255, 20)
        draw.line([slash_start, slash_end], fill=slash_color, width=2)
        for frac in [0.2, 0.4, 0.6, 0.8]:
            sx = int(slash_start[0] + (slash_end[0] - slash_start[0]) * frac)
            sy = int(slash_start[1] + (slash_end[1] - slash_start[1]) * frac)
            draw.line([(sx - 8, sy - 8), (sx + 8, sy + 8)], fill=(255, 255, 255), width=2)
            draw.line([(sx + 8, sy - 8), (sx - 8, sy + 8)], fill=(255, 255, 255), width=2)

        # 6. Ultra-Clean Cinematic Letterbox Borders & Corner Accents
        margin = int(width * 0.05)
        draw.rectangle([(margin, margin), (width - margin, height - margin)], outline=(40, 50, 80), width=1)

        corner_len = int(width * 0.035)
        corners = [
            (margin, margin),
            (width - margin, margin),
            (margin, height - margin),
            (width - margin, height - margin),
        ]
        accent_col = (255, 42, 133) if is_anime else (0, 242, 254)
        for cx, cy in corners:
            dx = corner_len if cx == margin else -corner_len
            dy = corner_len if cy == margin else -corner_len
            draw.line([(cx, cy), (cx + dx, cy)], fill=accent_col, width=3)
            draw.line([(cx, cy), (cx, cy + dy)], fill=accent_col, width=3)

        # 7. Top Header Meta
        category, title, subtitle, quote = self._resolve_copy(prompt, is_anime)
        font_meta = _load_font(int(width * 0.018), bold=True)
        draw.text((margin + 28, margin + 24), f"// {category}", fill=(0, 242, 254), font=font_meta)
        draw.text((width - margin - 220, margin + 24), "ORIGINAL ARTWORK", fill=(140, 160, 200), font=font_meta)
        draw.line([(margin + 28, margin + 52), (width - margin - 28, margin + 52)], fill=(30, 38, 60), width=1)

        # 8. Main Cinematic Title (Bold, Centered, Letterbox Style)
        font_title = _load_font(int(width * 0.046), bold=True)
        title_display = "  ".join(title.replace(" ", "").upper()) if len(title) <= 15 else title.upper()
        try:
            bbox = draw.textbbox((0, 0), title_display, font=font_title)
            tw = bbox[2] - bbox[0]
        except Exception:
            tw = len(title_display) * 26
        tx = max(margin + 28, (width - tw) // 2)
        draw.text((tx, int(height * 0.71)), title_display, fill=(255, 255, 255), font=font_title)

        # Subtitle
        font_sub = _load_font(int(width * 0.020), bold=True)
        try:
            sbox = draw.textbbox((0, 0), subtitle.upper(), font=font_sub)
            sw = sbox[2] - sbox[0]
        except Exception:
            sw = len(subtitle) * 12
        sx = max(margin + 28, (width - sw) // 2)
        draw.text((sx, int(height * 0.77)), subtitle.upper(), fill=(0, 242, 254), font=font_sub)

        # 9. Standalone Quote / Key Message
        font_quote = _load_font(int(width * 0.021), bold=False)
        q_lines = self._wrap_text(quote, max_chars=46)[:2]
        qy = int(height * 0.815)
        for ql in q_lines:
            try:
                qbox = draw.textbbox((0, 0), ql, font=font_quote)
                qw = qbox[2] - qbox[0]
            except Exception:
                qw = len(ql) * 12
            qx = max(margin + 28, (width - qw) // 2)
            draw.text((qx, qy), ql, fill=(210, 220, 240), font=font_quote)
            qy += int(height * 0.032)

        # 10. Clean Single Post Footer (Padded, No Border Overlaps)
        footer_y = height - margin - int(height * 0.045)
        draw.line([(margin + 28, footer_y - 12), (width - margin - 28, footer_y - 12)], fill=(30, 38, 60), width=1)

        font_footer = _load_font(int(width * 0.018), bold=True)
        draw.text((margin + 28, footer_y), "LIMITED EDITION KEY VISUAL", fill=(120, 140, 175), font=font_footer)
        draw.text((width - margin - 220, footer_y), "@ANIME_AI_INDIA", fill=accent_col, font=font_footer)

        return img

    def _resolve_copy(self, prompt: str, is_anime: bool) -> tuple[str, str, str, str]:
        if is_anime:
            category = "ANIME PHILOSOPHY // 01"
            title = "A W A K E N I N G"
            subtitle = "THE ARCHETYPE OF UNSTOPPABLE FOCUS"
            quote = '"The world only sees the final blow. They never see the ten thousand hours in the shadows."'
        else:
            category = "CREATOR SYSTEM // 01"
            title = "A U T O N O M O U S"
            subtitle = "THE BLUEPRINT FOR ZERO-TOUCH CREATION"
            quote = '"Replace repetitive grunt work with deterministic intelligence and amplify your real craft."'
        return category, title, subtitle, quote

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
