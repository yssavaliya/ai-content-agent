from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .base import BaseAgent
from ..database.connection import DatabaseConnection
from ..opencode.client import OpenCodeClient, OpenCodeError
from ..prompts.manager import PromptManager

logger = logging.getLogger(__name__)

SCORE_FIELDS = (
    "educational_score",
    "originality_score",
    "engagement_score",
    "relevance_score",
)


class PlannerAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "PlannerAgent"

    @property
    def description(self) -> str:
        return "Generates multiple content ideas and selects the best one."

    @property
    def input_schema(self) -> dict[str, str]:
        return {
            "research_output": "Structured output from ResearchAgent",
        }

    @property
    def output_schema(self) -> dict[str, str]:
        return {
            "ideas": "List of candidate ideas with scores",
            "selected_idea": "Best idea selected for creation",
        }

    def __init__(
        self,
        prompt_manager: PromptManager | None = None,
        opencode_client: OpenCodeClient | None = None,
        database: DatabaseConnection | None = None,
    ) -> None:
        self.prompt_manager = prompt_manager or PromptManager(prompt_dir=Path("src/ai_content_agent/prompts"))
        self.opencode_client = opencode_client
        self.database = database
        self.max_attempts = 2

    def execute(self, inputs: dict[str, object]) -> dict[str, object]:
        research_output = inputs["research_output"]
        prompt_text = self.prompt_manager.render("planner.md", {
            "research_json": json.dumps(research_output, indent=2, default=str),
        })

        last_error: Exception | None = None
        if self.opencode_client is None:
            self.opencode_client = OpenCodeClient()

        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.opencode_client.run([], input_text=prompt_text)
                payload = json.loads(response.stdout)
                validated = self._validate_payload(payload)
                logger.info("PlannerAgent generated %s ideas (attempt %s)", len(validated["ideas"]), attempt)
                return validated
            except (OpenCodeError, ValueError) as exc:
                last_error = exc
                if attempt == self.max_attempts:
                    logger.error("PlannerAgent failed after %s attempts: %s", attempt, exc)
                    raise RuntimeError(f"PlannerAgent failed after {attempt} attempts: {exc}") from exc
                logger.warning("PlannerAgent attempt %s/%s failed (%s); retrying", attempt, self.max_attempts, exc)
        raise RuntimeError("PlannerAgent encountered an unknown failure") from last_error

    def _validate_payload(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Planner output must be a JSON object")

        for field in ("ideas", "selected_idea"):
            if field not in payload:
                raise ValueError(f"Missing required planner field: {field}")

        ideas = payload["ideas"]
        if not isinstance(ideas, list) or not ideas:
            raise ValueError("ideas must be a non-empty list")
        for idea in ideas:
            if not isinstance(idea, dict):
                raise ValueError("Each planner idea must be a JSON object")
            self._validate_scored_idea(idea, "idea")

        selected_idea = payload["selected_idea"]
        if not isinstance(selected_idea, dict):
            raise ValueError("selected_idea must be a JSON object")
        self._validate_scored_idea(selected_idea, "selected_idea")

        return payload

    def _validate_scored_idea(self, idea: dict[str, Any], label: str) -> None:
        if not isinstance(idea.get("idea"), str) or not idea["idea"].strip():
            raise ValueError(f"{label}.idea must be a non-empty string")
        for field in SCORE_FIELDS:
            if field not in idea:
                raise ValueError(f"Missing required planner field: {label}.{field}")
            if not isinstance(idea[field], (int, float)):
                raise ValueError(f"{label}.{field} must be numeric")
