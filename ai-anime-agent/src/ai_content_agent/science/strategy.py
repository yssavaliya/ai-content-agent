from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..database.connection import DatabaseConnection
from ..timestamps import utc_now_iso

logger = logging.getLogger(__name__)


class StrategyGovernance:
    """Applies evidence-backed strategy changes only when thresholds are met."""

    def __init__(
        self,
        strategy_path: str | Path,
        database: DatabaseConnection | None = None,
        min_sample_size: int = 10,
        min_effect: float = 0.15,
        apply_threshold: float = 0.6,
    ) -> None:
        self.strategy_path = Path(strategy_path)
        self.database = database
        self.min_sample_size = min_sample_size
        self.min_effect = min_effect
        self.apply_threshold = apply_threshold

    def _get_database(self) -> DatabaseConnection:
        if self.database is None:
            self.database = DatabaseConnection()
        return self.database

    def _gates_met(self, recommendation: dict[str, Any]) -> tuple[bool, str]:
        sample_size = int(recommendation.get("sample_size") or 0)
        effect = float(recommendation.get("observed_effect") or 0.0)
        confidence = float(recommendation.get("confidence") or 0.0)

        if sample_size < self.min_sample_size:
            return False, (
                f"sample size {sample_size} < min {self.min_sample_size}"
            )
        if abs(effect) < self.min_effect:
            return False, f"|effect| {abs(effect):.3f} < min {self.min_effect}"
        if confidence < self.apply_threshold:
            return False, f"confidence {confidence:.2f} < apply threshold {self.apply_threshold}"
        return True, ""

    def apply_recommendation(
        self,
        recommendation: dict[str, Any],
        trigger: str,
    ) -> dict[str, Any]:
        passed, reason = self._gates_met(recommendation)
        if not passed:
            logger.info("Strategy change rejected for trigger %s: %s", trigger, reason)
            return {"applied": False, "reason": reason}

        if not self.strategy_path.exists():
            return {"applied": False, "reason": f"strategy file not found: {self.strategy_path}"}

        guideline = str(recommendation.get("strategy_guideline") or "").strip()
        if not guideline:
            return {"applied": False, "reason": "recommendation has no strategy_guideline"}

        previous_text = self.strategy_path.read_text(encoding="utf-8")
        if guideline in previous_text:
            return {"applied": False, "reason": "guideline already present in strategy"}

        block = (
            f"\n\n## Evidence-backed guidance ({utc_now_iso()})\n"
            f"**Trigger:** {trigger}\n"
            f"**Variable:** {recommendation.get('variable', 'unknown')}\n"
            f"**Observed effect (Cohen's d):** {float(recommendation.get('observed_effect') or 0.0):.3f}\n"
            f"**Sample size:** {int(recommendation.get('sample_size') or 0)}\n"
            f"**Confidence:** {float(recommendation.get('confidence') or 0.0):.2f}\n"
            f"**Rationale:** {recommendation.get('rationale', '')}\n"
            f"**Guideline:** {guideline}"
        )
        new_text = previous_text + block
        self.strategy_path.write_text(new_text, encoding="utf-8")

        db = self._get_database()
        cursor = db.execute(
            "INSERT INTO strategy_history(applied_at, trigger, recommendation_id, previous_text, new_text, notes) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                utc_now_iso(),
                trigger,
                recommendation.get("recommendation_id"),
                previous_text,
                new_text,
                recommendation.get("rationale", ""),
            ),
        )
        logger.info("Applied strategy guideline for trigger %s (history_id=%s)", trigger, cursor.lastrowid)
        return {
            "applied": True,
            "strategy_path": str(self.strategy_path),
            "history_id": cursor.lastrowid,
            "new_guideline": guideline,
        }
