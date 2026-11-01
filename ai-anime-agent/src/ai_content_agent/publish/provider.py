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


class PublishUnavailable(RuntimeError):
    """The publisher refused to take the post for a reason a human must fix (queue full, plan limit...).

    Unlike a crash, the content is kept: the pipeline saves a post kit and alerts instead of failing the run.
    """


class Publisher(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def publish(self, package_path: str) -> PublishResult:
        raise NotImplementedError
