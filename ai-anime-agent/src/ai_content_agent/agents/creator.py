from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from .base import BaseAgent, RETRY_BACKOFF_SECONDS
from ..database.connection import DatabaseConnection
from ..opencode.client import OpenCodeClient, OpenCodeError, extract_json_text
from ..prompts.manager import PromptManager

logger = logging.getLogger(__name__)


class CreatorAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "CreatorAgent"

    @property
    def description(self) -> str:
        return "Creates a post draft based on the selected content idea."

    @property
    def input_schema(self) -> dict[str, str]:
        return {
            "selected_idea": "Selected idea from PlannerAgent",
            "identity": "Path to identity documentation",
            "constitution": "Path to constitution documentation",
            "strategy": "Path to strategy documentation",
        }

    @property
    def output_schema(self) -> dict[str, str]:
        return {
            "carousel_outline": "Outline of post carousel slides",
            "caption": "Suggested post caption",
            "cta": "Call to action text",
            "hashtags": "List of hashtags",
            "image_prompt": "Prompt for the image provider",
            "alt_text": "Accessible alt text describing the generated image",
        }

    def __init__(
        self,
        prompt_manager: PromptManager | None = None,
        opencode_client: OpenCodeClient | None = None,
        database: DatabaseConnection | None = None,
    ) -> None:
        self.prompt_manager = prompt_manager or PromptManager()
        self.opencode_client = opencode_client
        self.database = database
        self.max_attempts = 3

    def execute(self, inputs: dict[str, object]) -> dict[str, object]:
        selected_idea = inputs["selected_idea"]
        identity_path = Path(inputs["identity"])
        constitution_path = Path(inputs["constitution"])
        strategy_path = Path(inputs["strategy"])
        market_path = Path(inputs["market"])

        if not identity_path.exists():
            raise FileNotFoundError(f"Identity document not found: {identity_path}")
        if not constitution_path.exists():
            raise FileNotFoundError(f"Constitution document not found: {constitution_path}")
        if not strategy_path.exists():
            raise FileNotFoundError(f"Strategy document not found: {strategy_path}")
        if not market_path.exists():
            raise FileNotFoundError(f"Market document not found: {market_path}")

        identity = identity_path.read_text(encoding="utf-8")
        constitution = constitution_path.read_text(encoding="utf-8")
        strategy = strategy_path.read_text(encoding="utf-8")
        market = market_path.read_text(encoding="utf-8")
        prompt_text = self.prompt_manager.render("creator.md", {
            "selected_idea": json.dumps(selected_idea, indent=2, default=str),
            "identity": identity,
            "constitution": constitution,
            "strategy": strategy,
            "market": market,
        })

        last_error: Exception | None = None
        if self.opencode_client is None:
            self.opencode_client = OpenCodeClient()

        for attempt in range(1, self.max_attempts + 1):
            raw = ""
            try:
                response = self.opencode_client.run([], input_text=prompt_text, label=self.name)
                raw = response.stdout or ""
                payload = json.loads(extract_json_text(raw))
                validated = self._validate_payload(payload)
                logger.info("CreatorAgent produced draft caption=%r (attempt %s)", validated["caption"], attempt)
                return validated
            except (OpenCodeError, ValueError) as exc:
                last_error = exc
                raw_preview = (getattr(exc, "stdout", None) or raw or "")[:300]
                if attempt == self.max_attempts:
                    logger.error("CreatorAgent failed after %s attempts: %s (raw=%r)", attempt, exc, raw_preview)
                    raise RuntimeError(f"CreatorAgent failed after {attempt} attempts: {exc}") from exc
                logger.warning("CreatorAgent attempt %s/%s failed (%s) raw=%r; retrying", attempt, self.max_attempts, exc, raw_preview)
                time.sleep(RETRY_BACKOFF_SECONDS)
        raise RuntimeError("CreatorAgent encountered an unknown failure") from last_error

    def _validate_payload(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Creator output must be a JSON object")

        required_fields = [
            "carousel_outline",
            "caption",
            "cta",
            "hashtags",
            "image_prompt",
            "alt_text",
        ]
        for field in required_fields:
            if field not in payload:
                raise ValueError(f"Missing required creator field: {field}")

        if not isinstance(payload["carousel_outline"], list) or not payload["carousel_outline"]:
            raise ValueError("carousel_outline must be a non-empty list")
        for slide in payload["carousel_outline"]:
            if not isinstance(slide, str) or not slide.strip():
                raise ValueError("carousel_outline must contain non-empty strings")

        for field in ("caption", "cta", "image_prompt", "alt_text"):
            if not isinstance(payload[field], str) or not payload[field].strip():
                raise ValueError(f"{field} must be a non-empty string")

        if not isinstance(payload["hashtags"], list) or not payload["hashtags"]:
            raise ValueError("hashtags must be a non-empty list")
        for tag in payload["hashtags"]:
            if not isinstance(tag, str) or not tag.strip():
                raise ValueError("hashtags must contain non-empty strings")

        return payload
