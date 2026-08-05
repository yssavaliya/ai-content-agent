from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ImageResult:
    provider: str
    prompt: str
    file_path: str
    metadata: dict[str, Any]


class ImageProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def generate(self, prompt: str) -> ImageResult:
        raise NotImplementedError
