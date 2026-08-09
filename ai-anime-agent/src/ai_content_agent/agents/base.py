from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AgentSchema:
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]


class BaseAgent(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def description(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def input_schema(self) -> dict[str, Any]:
        raise NotImplementedError

    @property
    @abstractmethod
    def output_schema(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def execute(self, inputs: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError
