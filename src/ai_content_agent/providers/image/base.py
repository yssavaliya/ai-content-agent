from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ImageRequest:
    prompt: str
    brand_style: str
    aspect_ratio: str
    # The post's opening line. Providers that draw text (the offline Pillow poster) use it so every poster
    # says something about the actual post instead of one fixed quote.
    headline: str = ""


@dataclass(frozen=True)
class ImageResult:
    provider: str
    prompt: str
    file_path: str
    metadata: dict[str, Any]


class BaseImageProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def validate(self, request: ImageRequest) -> None:
        raise NotImplementedError

    @abstractmethod
    def generate(self, request: ImageRequest) -> ImageResult:
        raise NotImplementedError
