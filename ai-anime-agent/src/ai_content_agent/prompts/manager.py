from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from string import Template
from typing import Any


PACKAGED_PROMPT_DIR = Path(__file__).resolve().parent


class PromptError(ValueError):
    pass


class PromptManager:
    def __init__(self, prompt_dir: str | Path | None = None) -> None:
        self.prompt_dir = Path(prompt_dir) if prompt_dir else PACKAGED_PROMPT_DIR

    @lru_cache(maxsize=32)
    def load_prompt(self, name: str) -> str:
        prompt_path = self.prompt_dir / name
        if not prompt_path.exists():
            raise PromptError(f"Prompt file not found: {prompt_path}")
        return prompt_path.read_text(encoding="utf-8")

    def render(self, name: str, variables: dict[str, Any]) -> str:
        template = Template(self.load_prompt(name))
        try:
            return template.substitute(variables)
        except KeyError as exc:
            raise PromptError(f"Missing prompt variable: {exc.args[0]}") from exc
