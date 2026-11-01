from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..agents.scientist import ScientistAgent
from ..analytics.collector import AnalyticsCollector
from ..analytics.registry import AnalyticsRegistry
from ..database.connection import DatabaseConnection
from ..growth.dashboard import build_plan, collect_dashboard_data, generate_dashboard
from ..growth.followers import (
    FollowerCount,
    FollowerSourceError,
    build_follower_source,
    record_snapshot,
)
from ..growth.health import check_health
from ..notifications.notifier import Notifier
from ..science.experiments import ExperimentRepository, compute_experiment_result
from ..science.strategy import StrategyGovernance
from ..settings import Settings, current_settings
from ..timestamps import utc_now_iso
from .pipeline import ContentPipeline
from .run_lock import RunLock, lock_path_for_database

logger = logging.getLogger(__name__)

DEFAULT_EXPERIMENT_NAME = "initial-content-strategy"
HOOK_STYLE_VARIABLE = "hook-style"
HOOK_CONTROL = (
    "open the caption with a bold, declarative claim stated as a single confident sentence "
    "(the current default hook style)."
)
HOOK_VARIANT = (
    "open the caption with a curiosity-gap question of at most 12 words that makes the viewer need to read "
    "the next line; do not answer it in the first sentence."
)
PLACEHOLDER_VARIANT = "Experimentally varied content approach"


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

    def run_followers(self, manual_count: int | None = None) -> dict[str, Any]:
        """Record today's follower count: from the Instagram Graph API, or a number you supply."""
        with self._run_lock():
            db = DatabaseConnection()
            try:
                if manual_count is not None:
                    count = FollowerCount(followers=manual_count, media_count=None, source="manual")
                else:
                    source = build_follower_source(self.settings)
                    if source is None:
                        return {
                            "stage": "followers",
                            "ok": False,
                            "note": "No follower source configured. Set INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_ACCOUNT_ID "
                            "(Business/Creator account) or record a count with: ai-content-agent followers <number>",
                        }
                    try:
                        count = source.fetch()
                    except FollowerSourceError as exc:
                        self.notifier.send_failure(
                            subject="AI Content Agent: follower count unavailable",
                            body=str(exc),
                            metadata={"color": 15158332},
                        )
                        raise
                record_snapshot(db, count)
                return {"stage": "followers", "ok": True, "followers": count.followers, "source": count.source}
            finally:
                db.close()

    def run_dashboard(self, output_path: str | Path = "dashboard/index.html") -> dict[str, Any]:
        db = DatabaseConnection()
        try:
            path = generate_dashboard(db, self.settings, output_path)
            return {"stage": "dashboard", "ok": True, "path": str(path)}
        finally:
            db.close()

    def run_milestone(self) -> dict[str, Any]:
        db = DatabaseConnection()
        try:
            data = collect_dashboard_data(db, self.settings)
            return {"stage": "milestone", "ok": True, "milestone": data["milestone"], "day_gain": data["day_gain"],
                    "week_gain": data["week_gain"]}
        finally:
            db.close()

    def run_health(self) -> dict[str, Any]:
        """Alert the configured channels when something needs a human."""
        db = DatabaseConnection()
        try:
            issues = check_health(db, build_plan(self.settings, db, datetime.now(timezone.utc).date()))
            if issues:
                self.notifier.send_failure(
                    subject="AI Content Agent: attention needed",
                    body="\n".join(f"- {issue}" for issue in issues),
                    metadata={"color": 15158332},
                )
            return {"stage": "health", "ok": not issues, "issues": issues}
        finally:
            db.close()

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
            self._upgrade_placeholder_experiment(db, active[0])
            return active[0].id
        return repository.create(
            name=DEFAULT_EXPERIMENT_NAME,
            description="Does a curiosity-gap opening earn a higher engagement rate than a bold declarative opening?",
            hypothesis="Opening with a curiosity-gap question increases engagement rate versus a declarative claim.",
            variable=HOOK_STYLE_VARIABLE,
            control_description=HOOK_CONTROL,
            variant_description=HOOK_VARIANT,
            min_effect=self.settings.scientist_min_effect,
            confidence_threshold=self.settings.scientist_apply_threshold,
        )

    @staticmethod
    def _upgrade_placeholder_experiment(db: DatabaseConnection, experiment: Any) -> None:
        """Early databases hold an experiment whose two arms were vague labels that changed nothing.

        Give it the concrete treatment so its arms genuinely differ. Only the descriptions change; posts
        already assigned keep their arm.
        """
        if experiment.variant_description == PLACEHOLDER_VARIANT:
            db.execute(
                "UPDATE experiments SET variable = ?, control_description = ?, variant_description = ?, "
                "hypothesis = ? WHERE id = ?",
                (HOOK_STYLE_VARIABLE, HOOK_CONTROL, HOOK_VARIANT,
                 "Opening with a curiosity-gap question increases engagement rate versus a declarative claim.",
                 experiment.id),
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
