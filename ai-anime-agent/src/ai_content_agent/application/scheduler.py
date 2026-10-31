from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..agents.scientist import ScientistAgent
from ..analytics.collector import AnalyticsCollector
from ..analytics.registry import AnalyticsRegistry
from ..database.connection import DatabaseConnection
from ..notifications.notifier import Notifier
from ..science.experiments import ExperimentRepository, compute_experiment_result
from ..science.strategy import StrategyGovernance
from ..settings import Settings, current_settings
from ..timestamps import utc_now_iso
from .pipeline import ContentPipeline
from .run_lock import RunLock, lock_path_for_database

logger = logging.getLogger(__name__)

DEFAULT_EXPERIMENT_NAME = "initial-content-strategy"


class Scheduler:
    """Coordinates the daily, analytics, scientist, and monthly jobs."""

    def __init__(
        self,
        settings: Settings | None = None,
        notifier: Notifier | None = None,
        strategy_path: str | Path = "brain/strategy.md",
    ) -> None:
        self.settings = settings or current_settings()
        self.notifier = notifier or Notifier.from_settings(self.settings)
        self.strategy_path = Path(strategy_path)

    def _run_lock(self) -> RunLock:
        return RunLock(lock_path_for_database(self.settings.database_path))

    def run_daily(self) -> dict[str, Any]:
        with self._run_lock():
            try:
                provider = AnalyticsRegistry.build_provider(self.settings)
                if provider:
                    logger.info('Running pre-generation analytics collection via %s...', provider.name)
                    collector = AnalyticsCollector(provider, max_age_days=self.settings.analytics_max_age_days)
                    collector.collect()
            except Exception as exc:
                logger.warning('Pre-run analytics collection failed: %s', exc)

            try:
                self._run_scientist_locked()
            except Exception as exc:
                logger.warning('Pre-run scientist analysis failed: %s', exc)

            pipeline = ContentPipeline(settings=self.settings, notifier=self.notifier)
            try:
                package = pipeline.run()
                return {"stage": "daily", "ok": True, "run_id": package.get("run_id"), "package": package}
            finally:
                pipeline.close()

    def run_analytics(self) -> dict[str, Any]:
        with self._run_lock():
            provider = AnalyticsRegistry.build_provider(self.settings)
            collector = AnalyticsCollector(provider, max_age_days=self.settings.analytics_max_age_days)
            summary = collector.collect()
            if summary.get("enabled"):
                self.notifier.send_success(
                    subject="AI Content Agent: analytics collected",
                    body=(
                        f"Posts considered: {summary.get('posts_considered')}\n"
                        f"Collected: {summary.get('collected')}\n"
                        f"Failed: {summary.get('failed')}\n"
                        f"Collected at: {summary.get('collected_at')}"
                    ),
                    metadata={"color": 3447003},
                )
            return {"stage": "analytics", "ok": True, "summary": summary}

    def _ensure_experiment(self, db: DatabaseConnection) -> int:
        repository = ExperimentRepository(db)
        active = repository.list_active()
        if active:
            return active[0].id
        return repository.create(
            name=DEFAULT_EXPERIMENT_NAME,
            description="Initial content strategy experiment comparing the default approach against a variant.",
            hypothesis="A systematically varied content approach outperforms the current default.",
            variable="content-approach",
            control_description="Current default content approach",
            variant_description="Experimentally varied content approach",
            min_effect=self.settings.scientist_min_effect,
            confidence_threshold=self.settings.scientist_apply_threshold,
        )

    def run_scientist(self) -> dict[str, Any]:
        with self._run_lock():
            return self._run_scientist_locked()

    def _run_scientist_locked(self) -> dict[str, Any]:
        db = DatabaseConnection()
        try:
            experiment_id = self._ensure_experiment(db)
            experiment_repository = ExperimentRepository(db)
            active = experiment_repository.list_active()
            results = [
                compute_experiment_result(
                    experiment.id,
                    db,
                    min_sample_size=self.settings.scientist_min_sample_size,
                    min_effect=self.settings.scientist_min_effect,
                ).to_dict()
                for experiment in active
            ]

            if all(result["n_control"] + result["n_variant"] == 0 for result in results):
                summary: dict[str, Any] = {
                    "stage": "scientist",
                    "ok": True,
                    "experiment_id": experiment_id,
                    "results": results,
                    "note": "no posts with analytics yet; experiment still collecting",
                }
                logger.info("Scientist: no analytics yet for experiment %s", experiment_id)
                return summary

            scientist = ScientistAgent(database=db)
            scientist_output = scientist.execute(
                {
                    "experiment_results": results,
                    "identity": "brain/identity.md",
                    "constitution": "brain/constitution.md",
                    "strategy": "brain/strategy.md",
                }
            )

            governance = StrategyGovernance(
                strategy_path=self.strategy_path,
                database=db,
                min_sample_size=self.settings.scientist_min_sample_size,
                min_effect=self.settings.scientist_min_effect,
                apply_threshold=self.settings.scientist_apply_threshold,
            )

            outcomes: list[dict[str, Any]] = []
            for recommendation in scientist_output.get("recommendations", []):
                outcome = governance.apply_recommendation(
                    recommendation, trigger="scientist"
                )
                outcomes.append(
                    {
                        "variable": recommendation.get("variable"),
                        "applied": outcome["applied"],
                        "reason": outcome.get("reason"),
                    }
                )

            completed: list[int] = []
            for experiment in active:
                result = next(
                    (r for r in results if r["experiment_id"] == experiment.id), None
                )
                if result and result["significant"]:
                    experiment_repository.complete(experiment.id)
                    completed.append(experiment.id)

            summary = {
                "stage": "scientist",
                "ok": True,
                "experiment_id": experiment_id,
                "results": results,
                "recommendations": scientist_output.get("recommendations"),
                "summary": scientist_output.get("summary"),
                "outcomes": outcomes,
                "completed_experiments": completed,
                "applied_count": sum(1 for o in outcomes if o["applied"]),
            }
            self.notifier.send_success(
                subject="AI Content Agent: scientist analysis complete",
                body=self._scientist_body(summary),
                metadata={"color": 3447003},
            )
            return summary
        finally:
            db.close()

    def _scientist_body(self, summary: dict[str, Any]) -> str:
        lines = [
            f"Experiments analyzed: {len(summary['results'])}",
            f"Recommendations: {len(summary.get('recommendations') or [])}",
            f"Applied: {summary['applied_count']}",
            f"Completed experiments: {', '.join(map(str, summary['completed_experiments'])) or 'none'}",
            f"Summary: {summary.get('summary', '')}",
        ]
        return "\n".join(lines)

    def run_monthly(self) -> dict[str, Any]:
        with self._run_lock():
            return self._run_monthly_locked()

    def _run_monthly_locked(self) -> dict[str, Any]:
        db = DatabaseConnection()
        try:
            digest = self._monthly_digest(db)
            self.notifier.send_success(
                subject="AI Content Agent: monthly report",
                body=(
                    f"Published posts: {digest['published_posts']}\n"
                    f"Experiments completed: {digest['experiments_completed']}\n"
                    f"Strategy changes applied: {digest['strategy_changes']}\n"
                    f"Analytics observations: {digest['observations']}\n"
                    f"Generated at: {utc_now_iso()}"
                ),
                metadata={"color": 3447003},
            )
            return {"stage": "monthly", "ok": True, "digest": digest}
        finally:
            db.close()

    def _monthly_digest(self, db: DatabaseConnection) -> dict[str, int]:
        with db.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM posts")
            published_posts = int(cursor.fetchone()[0])
            cursor.execute("SELECT COUNT(*) FROM experiments WHERE status = 'completed'")
            experiments_completed = int(cursor.fetchone()[0])
            cursor.execute("SELECT COUNT(*) FROM strategy_history")
            strategy_changes = int(cursor.fetchone()[0])
            cursor.execute("SELECT COUNT(*) FROM observations")
            observations = int(cursor.fetchone()[0])
        return {
            "published_posts": published_posts,
            "experiments_completed": experiments_completed,
            "strategy_changes": strategy_changes,
            "observations": observations,
        }
