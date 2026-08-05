from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ImageRequest:
    prompt: str
    brand_style: str
    aspect_ratio: str


@dataclass(frozen=True)
class ImageResult:
    provider: str
    prompt: str
    file_path: str
    metadata: dict[str, Any]
