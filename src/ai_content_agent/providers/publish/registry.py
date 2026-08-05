from __future__ import annotations

from typing import ClassVar, Dict, Type

from .base import BasePublisher
from .exceptions import PublishError


class PublisherRegistry:
    _publishers: ClassVar[Dict[str, Type[BasePublisher]]] = {}

    @classmethod
    def register(cls, provider: Type[BasePublisher]) -> Type[BasePublisher]:
        if provider.name in cls._publishers:
            raise PublishError(f"Publisher already registered: {provider.name}")
        cls._publishers[provider.name] = provider
        return provider

    @classmethod
    def get_provider(cls, name: str) -> Type[BasePublisher]:
        if name not in cls._publishers:
            raise PublishError(f"Unknown publisher: {name}")
        return cls._publishers[name]

    @classmethod
    def list_providers(cls) -> list[str]:
        return list(cls._publishers)
