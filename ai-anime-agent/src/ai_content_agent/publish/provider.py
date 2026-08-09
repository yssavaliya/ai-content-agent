from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PublishResult:
    provider: str
    status: str
    published_id: str
    metadata: dict[str, Any]


class Publisher(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def publish(self, package_path: str) -> PublishResult:
        raise NotImplementedError
