from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ..provider import ImageProvider, ImageResult


class LocalImageProvider(ImageProvider):
    @property
    def name(self) -> str:
        return "local"

    def generate(self, prompt: str) -> ImageResult:
        now = datetime.utcnow()
        output_dir = Path("images") / now.strftime("%Y") / now.strftime("%m") / now.strftime("%d")
        output_dir.mkdir(parents=True, exist_ok=True)
        file_path = output_dir / f"image_{now.strftime('%H%M%S')}.txt"
        file_path.write_text(
            json.dumps({"prompt": prompt, "generated_at": now.isoformat() + "Z"}, indent=2),
            encoding="utf-8",
        )
        return ImageResult(
            provider=self.name,
            prompt=prompt,
            file_path=str(file_path),
            metadata={"created_at": now.isoformat() + "Z", "placeholder": True},
        )
