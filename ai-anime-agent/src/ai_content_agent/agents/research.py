from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..agents.base import BaseAgent
from ..database.connection import DatabaseConnection
from ..opencode.client import OpenCodeClient, OpenCodeError
from ..prompts.manager import PromptManager
from ..timestamps import utc_now_iso

logger = logging.getLogger(__name__)


class ResearchAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "ResearchAgent"

    @property
    def description(self) -> str:
        return "Collects trend and strategy information to recommend a content topic."

    @property
    def input_schema(self) -> dict[str, str]:
        return {
            "identity": "Path to identity documentation",
            "strategy": "Path to strategy documentation",
            "market": "Path to market documentation",
            "prompt": "Path to research prompt",
        }

    @property
    def output_schema(self) -> dict[str, str]:
        return {
            "recommended_topic": "Selected topic for content",
            "audience_problem": "Audience problem the topic solves",
            "why_now": "Why this topic matters today",
            "hook": "Suggested post hook",
            "supporting_points": "Key supporting points for the research topic",
            "confidence": "Confidence score from 0 to 100",
            "reasoning": "Explanation of the chosen topic and recommendation",
            "timestamp": "ISO-formatted timestamp",
            "research_id": "ID of the persisted research record",
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
        identity_path = Path(inputs["identity"])
        strategy_path = Path(inputs["strategy"])
        market_path = Path(inputs["market"])
        prompt_name = str(inputs["prompt"])
        run_date = str(inputs.get("run_date") or datetime.now(timezone.utc).date().isoformat())

        if not identity_path.exists():
            raise FileNotFoundError(f"Identity document not found: {identity_path}")
        if not strategy_path.exists():
            raise FileNotFoundError(f"Strategy document not found: {strategy_path}")
        if not market_path.exists():
            raise FileNotFoundError(f"Market document not found: {market_path}")

        identity = identity_path.read_text(encoding="utf-8")
        strategy = strategy_path.read_text(encoding="utf-8")
        market = market_path.read_text(encoding="utf-8")
        prompt_text = self.prompt_manager.render(prompt_name, {
            "identity": identity,
            "strategy": strategy,
            "market": market,
            "run_date": run_date,
        })

        last_error: Exception | None = None
        if self.opencode_client is None:
            self.opencode_client = OpenCodeClient()

        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.opencode_client.run([], input_text=prompt_text, label=self.name)
                payload = json.loads(response.stdout)
                validated = self._validate_payload(payload)
                research_id = self._persist_research(validated)
                validated["research_id"] = research_id
                logger.info("ResearchAgent recommended topic=%r (research_id=%s)", validated["recommended_topic"], research_id)
                return validated
            except (OpenCodeError, ValueError) as exc:
                last_error = exc
                if attempt == self.max_attempts:
                    logger.error("ResearchAgent failed after %s attempts: %s", attempt, exc)
                    raise RuntimeError(f"ResearchAgent failed after {attempt} attempts: {exc}") from exc
                logger.warning("ResearchAgent attempt %s/%s failed (%s); retrying", attempt, self.max_attempts, exc)
        raise RuntimeError("ResearchAgent encountered an unknown failure") from last_error

    def _validate_payload(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Research output must be a JSON object")

        required_fields = [
            "recommended_topic",
            "audience_problem",
            "why_now",
            "hook",
            "supporting_points",
            "confidence",
            "reasoning",
            "timestamp",
        ]

        for field in required_fields:
            if field not in payload:
                raise ValueError(f"Missing required research field: {field}")

        if not isinstance(payload["recommended_topic"], str) or not payload["recommended_topic"].strip():
            raise ValueError("recommended_topic must be a non-empty string")
        if not isinstance(payload["audience_problem"], str) or not payload["audience_problem"].strip():
            raise ValueError("audience_problem must be a non-empty string")
        if not isinstance(payload["why_now"], str) or not payload["why_now"].strip():
            raise ValueError("why_now must be a non-empty string")
        if not isinstance(payload["hook"], str) or not payload["hook"].strip():
            raise ValueError("hook must be a non-empty string")
        if not isinstance(payload["supporting_points"], list) or not payload["supporting_points"]:
            raise ValueError("supporting_points must be a non-empty list")
        for point in payload["supporting_points"]:
            if not isinstance(point, str) or not point.strip():
                raise ValueError("supporting_points must contain non-empty strings")
        if not isinstance(payload["trend_signals"], list) or not payload["trend_signals"]:
            raise ValueError("trend_signals must be a non-empty list")
        for signal in payload["trend_signals"]:
            if not isinstance(signal, str) or not signal.strip():
                raise ValueError("trend_signals must contain non-empty strings")
        if not isinstance(payload["candidate_topics"], list) or not payload["candidate_topics"]:
            raise ValueError("candidate_topics must be a non-empty list")
        for topic in payload["candidate_topics"]:
            if not isinstance(topic, str) or not topic.strip():
                raise ValueError("candidate_topics must contain non-empty strings")
        if not isinstance(payload["confidence"], (int, float)):
            raise ValueError("confidence must be numeric")
        if not isinstance(payload["reasoning"], str) or not payload["reasoning"].strip():
            raise ValueError("reasoning must be a non-empty string")
        if not isinstance(payload["timestamp"], str) or not payload["timestamp"].strip():
            raise ValueError("timestamp must be a non-empty string")

        return payload

    def _persist_research(self, payload: dict[str, Any]) -> int:
        database = self.database or DatabaseConnection()
        own_database = self.database is None

        try:
            cursor = database.execute(
                "INSERT INTO research_raw(provider, title, source, summary, category, url, retrieved_at, normalized_at, raw_payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self.name,
                    payload["recommended_topic"],
                    "opencode-research",
                    payload["reasoning"],
                    "research",
                    None,
                    payload["timestamp"],
                    utc_now_iso(),
                    json.dumps(payload),
                ),
            )
            return cursor.lastrowid
        finally:
            if own_database:
                database.close()
