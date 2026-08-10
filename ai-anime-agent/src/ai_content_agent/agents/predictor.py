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
from ..timestamps import utc_now_iso

logger = logging.getLogger(__name__)

VIRALITY_LABELS = {"LOW", "MEDIUM", "HIGH"}


class PredictorAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "PredictorAgent"

    @property
    def description(self) -> str:
        return "Predicts the virality potential of the drafted post for Indian Instagram."

    @property
    def input_schema(self) -> dict[str, str]:
        return {
            "creator_output": "Structured output from CreatorAgent",
            "research_json": "Research output as JSON string",
            "review_json": "Reviewer output as JSON string",
            "market": "Path to market documentation",
            "recent_posts_json": "Recent post performance as JSON string",
        }

    @property
    def output_schema(self) -> dict[str, str]:
        return {
            "virality_score": "Virality score from 0 to 100",
            "virality_label": "LOW, MEDIUM, or HIGH",
            "virality_probability": "Estimated probability of going viral, 0 to 1",
            "key_factors": "List of top contributing factors",
            "risks": "List of risks that could stop virality",
            "reasoning": "Explanation of the prediction",
            "timestamp": "ISO-formatted timestamp",
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
        self.max_attempts = 3

    def execute(self, inputs: dict[str, object]) -> dict[str, object]:
        creator_output = inputs["creator_output"]
        research_json = str(inputs["research_json"])
        review_json = str(inputs["review_json"])
        recent_posts_json = str(inputs["recent_posts_json"])
        market_path = Path(inputs["market"])

        if not market_path.exists():
            raise FileNotFoundError(f"Market document not found: {market_path}")

        market = market_path.read_text(encoding="utf-8")
        prompt_text = self.prompt_manager.render("predictor.md", {
            "creator_output": json.dumps(creator_output, indent=2, default=str),
            "research_json": research_json,
            "review_json": review_json,
            "market": market,
            "recent_posts_json": recent_posts_json,
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
                logger.info(
                    "PredictorAgent predicted score=%s label=%s (attempt %s)",
                    validated["virality_score"],
                    validated["virality_label"],
                    attempt,
                )
                return validated
            except (OpenCodeError, ValueError) as exc:
                last_error = exc
                raw_preview = (getattr(exc, "stdout", None) or raw or "")[:300]
                if attempt == self.max_attempts:
                    logger.error("PredictorAgent failed after %s attempts: %s (raw=%r)", attempt, exc, raw_preview)
                    raise RuntimeError(f"PredictorAgent failed after {attempt} attempts: {exc}") from exc
                logger.warning("PredictorAgent attempt %s/%s failed (%s) raw=%r; retrying", attempt, self.max_attempts, exc, raw_preview)
                time.sleep(RETRY_BACKOFF_SECONDS)
        raise RuntimeError("PredictorAgent encountered an unknown failure") from last_error

    def _validate_payload(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Predictor output must be a JSON object")

        for field in ("virality_score", "virality_label", "virality_probability", "key_factors", "risks", "reasoning", "timestamp"):
            if field not in payload:
                raise ValueError(f"Missing required predictor field: {field}")

        score = payload["virality_score"]
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            raise ValueError("virality_score must be numeric")
        score = int(score)
        if not 0 <= score <= 100:
            raise ValueError("virality_score must be between 0 and 100")

        label = payload["virality_label"]
        if label not in VIRALITY_LABELS:
            raise ValueError("virality_label must be LOW, MEDIUM, or HIGH")

        probability = payload["virality_probability"]
        if not isinstance(probability, (int, float)) or isinstance(probability, bool):
            raise ValueError("virality_probability must be numeric")
        if not 0.0 <= float(probability) <= 1.0:
            raise ValueError("virality_probability must be between 0 and 1")

        for field in ("key_factors", "risks"):
            items = payload[field]
            if not isinstance(items, list) or not items:
                raise ValueError(f"{field} must be a non-empty list")
            for item in items:
                if not isinstance(item, str) or not item.strip():
                    raise ValueError(f"{field} must contain non-empty strings")

        if not isinstance(payload["reasoning"], str) or not payload["reasoning"].strip():
            raise ValueError("reasoning must be a non-empty string")
        if not isinstance(payload["timestamp"], str) or not payload["timestamp"].strip():
            raise ValueError("timestamp must be a non-empty string")

        payload["virality_score"] = score
        payload["virality_probability"] = float(probability)
        payload["timestamp"] = utc_now_iso()
        return payload

    def recent_posts_performance(self, limit: int = 10) -> str:
        """Return the last N published posts with engagement metrics as JSON, or '[]'."""
        database = self.database or DatabaseConnection()
        own_database = self.database is None
        try:
            rows = database.fetch_all(
                "SELECT p.caption, p.hashtags, p.topic, p.created_at, "
                "m.likes, m.comments, m.shares, m.saves, m.reach "
                "FROM posts p LEFT JOIN post_metrics m ON m.post_id = p.id "
                "ORDER BY p.id DESC LIMIT ?",
                (limit,),
            )
            return json.dumps(rows, default=str)
        finally:
            if own_database:
                database.close()
