from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PublishRequest:
    package_path: str
    package_metadata: dict[str, Any]


@dataclass(frozen=True)
class PublishResult:
    provider: str
    status: str
    publication_id: str
    timestamp: str
    errors: list[str]
    metadata: dict[str, Any]
