from __future__ import annotations

from pathlib import Path
from typing import ClassVar, Dict, Type

from .base import BaseImageProvider
from .exceptions import ImageProviderError


class ImageProviderRegistry:
    _providers: ClassVar[Dict[str, Type[BaseImageProvider]]] = {}

    @classmethod
    def register(cls, provider: Type[BaseImageProvider]) -> Type[BaseImageProvider]:
        if provider.name in cls._providers:
            raise ImageProviderError(f"Provider already registered: {provider.name}")
        cls._providers[provider.name] = provider
        return provider

    @classmethod
    def get_provider(cls, name: str) -> Type[BaseImageProvider]:
        if name not in cls._providers:
            raise ImageProviderError(f"Unknown image provider: {name}")
        return cls._providers[name]

    @classmethod
    def list_providers(cls) -> list[str]:
        return list(cls._providers)
