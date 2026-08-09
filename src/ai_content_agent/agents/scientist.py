from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .base import BaseAgent
from ..database.connection import DatabaseConnection
from ..opencode.client import OpenCodeClient, OpenCodeError
from ..prompts.manager import PromptManager
from ..timestamps import utc_now_iso

logger = logging.getLogger(__name__)

RECOMMENDATION_FIELDS = (
    "strategy_guideline",
    "rationale",
    "variable",
    "observed_effect",
    "sample_size",
    "confidence",
    "significance_p",
)


class ScientistAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "ScientistAgent"

    @property
    def description(self) -> str:
        return "Analyzes experiment evidence and recommends evidence-backed strategy changes."

    @property
    def input_schema(self) -> dict[str, str]:
        return {
            "experiment_results": "List of experiment result dictionaries",
            "identity": "Path to identity documentation",
            "constitution": "Path to constitution documentation",
            "strategy": "Path to strategy documentation",
        }

    @property
    def output_schema(self) -> dict[str, str]:
        return {
            "recommendations": "List of evidence-backed strategy recommendations",
            "summary": "Short summary of the analysis",
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
        experiment_results = inputs["experiment_results"]
        identity_path = Path(inputs["identity"])
        constitution_path = Path(inputs["constitution"])
        strategy_path = Path(inputs["strategy"])

        for doc_path in (identity_path, constitution_path, strategy_path):
            if not doc_path.exists():
                raise FileNotFoundError(f"Document not found: {doc_path}")

        identity = identity_path.read_text(encoding="utf-8")
        constitution = constitution_path.read_text(encoding="utf-8")
        strategy = strategy_path.read_text(encoding="utf-8")
        prompt_text = self.prompt_manager.render("scientist.md", {
            "experiment_results_json": json.dumps(experiment_results, indent=2, default=str),
            "identity": identity,
            "constitution": constitution,
            "strategy": strategy,
        })

        last_error: Exception | None = None
        if self.opencode_client is None:
            self.opencode_client = OpenCodeClient()

        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.opencode_client.run([], input_text=prompt_text, label=self.name)
                payload = json.loads(response.stdout)
                validated = self._validate_payload(payload)
                self._persist_analysis(validated)
                logger.info("ScientistAgent returned %s recommendations (attempt %s)", len(validated["recommendations"]), attempt)
                return validated
            except (OpenCodeError, ValueError) as exc:
                last_error = exc
                if attempt == self.max_attempts:
                    logger.error("ScientistAgent failed after %s attempts: %s", attempt, exc)
                    raise RuntimeError(f"ScientistAgent failed after {attempt} attempts: {exc}") from exc
                logger.warning("ScientistAgent attempt %s/%s failed (%s); retrying", attempt, self.max_attempts, exc)
        raise RuntimeError("ScientistAgent encountered an unknown failure") from last_error

    def _validate_payload(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Scientist output must be a JSON object")

        for field in ("recommendations", "summary"):
            if field not in payload:
                raise ValueError(f"Missing required scientist field: {field}")

        if not isinstance(payload["summary"], str) or not payload["summary"].strip():
            raise ValueError("summary must be a non-empty string")

        recommendations = payload["recommendations"]
        if not isinstance(recommendations, list):
            raise ValueError("recommendations must be a list")
        for index, recommendation in enumerate(recommendations):
            if not isinstance(recommendation, dict):
                raise ValueError(f"recommendations[{index}] must be a JSON object")
            for field in RECOMMENDATION_FIELDS:
                if field not in recommendation:
                    raise ValueError(f"Missing required scientist field: recommendations[{index}].{field}")
            if not isinstance(recommendation["strategy_guideline"], str) or not recommendation["strategy_guideline"].strip():
                raise ValueError(f"recommendations[{index}].strategy_guideline must be a non-empty string")
            if not isinstance(recommendation["observed_effect"], (int, float)):
                raise ValueError(f"recommendations[{index}].observed_effect must be numeric")
            if not isinstance(recommendation["sample_size"], (int, float)):
                raise ValueError(f"recommendations[{index}].sample_size must be numeric")
            if not isinstance(recommendation["confidence"], (int, float)):
                raise ValueError(f"recommendations[{index}].confidence must be numeric")

        return payload

    def _persist_analysis(self, payload: dict[str, Any]) -> int:
        database = self.database or DatabaseConnection()
        own_database = self.database is None
        try:
            cursor = database.execute(
                "INSERT INTO observations(collected_at, source, post_id, metric_name, metric_value, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    utc_now_iso(),
                    self.name,
                    None,
                    "scientist_analysis",
                    len(payload["recommendations"]),
                    json.dumps(payload),
                ),
            )
            return cursor.lastrowid
        finally:
            if own_database:
                database.close()
