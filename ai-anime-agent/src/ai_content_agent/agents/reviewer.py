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


class ReviewerAgent(BaseAgent):
    @property
    def name(self) -> str:
        return "ReviewerAgent"

    @property
    def description(self) -> str:
        return "Reviews created content for quality and brand alignment."

    @property
    def input_schema(self) -> dict[str, str]:
        return {
            "creator_output": "Structured output from CreatorAgent",
            "identity": "Path to identity documentation",
            "constitution": "Path to constitution documentation",
        }

    @property
    def output_schema(self) -> dict[str, str]:
        return {
            "status": "PASS or FAIL",
            "reasons": "List of review findings",
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
        self.max_attempts = 2

    def execute(self, inputs: dict[str, object]) -> dict[str, object]:
        creator_output = inputs["creator_output"]
        identity_path = Path(inputs["identity"])
        constitution_path = Path(inputs["constitution"])
        market_path = Path(inputs["market"])

        if not identity_path.exists():
            raise FileNotFoundError(f"Identity document not found: {identity_path}")
        if not constitution_path.exists():
            raise FileNotFoundError(f"Constitution document not found: {constitution_path}")
        if not market_path.exists():
            raise FileNotFoundError(f"Market document not found: {market_path}")

        identity = identity_path.read_text(encoding="utf-8")
        constitution = constitution_path.read_text(encoding="utf-8")
        market = market_path.read_text(encoding="utf-8")
        prompt_text = self.prompt_manager.render("reviewer.md", {
            "creator_output": json.dumps(creator_output, indent=2, default=str),
            "identity": identity,
            "constitution": constitution,
            "market": market,
        })

        last_error: Exception | None = None
        if self.opencode_client is None:
            self.opencode_client = OpenCodeClient()

        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.opencode_client.run([], input_text=prompt_text, label=self.name)
                payload = json.loads(response.stdout)
                validated = self._validate_payload(payload)
                logger.info("ReviewerAgent returned status=%s (attempt %s)", validated["status"], attempt)
                return validated
            except (OpenCodeError, ValueError) as exc:
                last_error = exc
                if attempt == self.max_attempts:
                    logger.error("ReviewerAgent failed after %s attempts: %s", attempt, exc)
                    raise RuntimeError(f"ReviewerAgent failed after {attempt} attempts: {exc}") from exc
                logger.warning("ReviewerAgent attempt %s/%s failed (%s); retrying", attempt, self.max_attempts, exc)
        raise RuntimeError("ReviewerAgent encountered an unknown failure") from last_error

    def _validate_payload(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Reviewer output must be a JSON object")

        for field in ("status", "reasons", "timestamp"):
            if field not in payload:
                raise ValueError(f"Missing required reviewer field: {field}")

        if payload["status"] not in {"PASS", "FAIL"}:
            raise ValueError("status must be either PASS or FAIL")

        if not isinstance(payload["reasons"], list) or not payload["reasons"]:
            raise ValueError("reasons must be a non-empty list")
        for reason in payload["reasons"]:
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError("reasons must contain non-empty strings")

        if not isinstance(payload["timestamp"], str) or not payload["timestamp"].strip():
            raise ValueError("timestamp must be a non-empty string")

        payload["timestamp"] = utc_now_iso()
        return payload
