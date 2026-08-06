from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..database.connection import DatabaseConnection
from ..timestamps import utc_now_iso
from . import statistics

VALID_ARMS = ("control", "variant")


@dataclass(frozen=True)
class Experiment:
    id: int
    name: str
    description: str
    started_at: str
    status: str
    hypothesis: str | None = None
    variable: str | None = None
    control_description: str | None = None
    variant_description: str | None = None
    min_effect: float | None = None
    confidence_threshold: float | None = None
    ended_at: str | None = None


@dataclass(frozen=True)
class ExperimentResult:
    experiment_id: int
    variable: str
    n_control: int
    n_variant: int
    control_mean: float
    variant_mean: float
    control_std: float
    variant_std: float
    cohens_d: float
    p_value: float
    winner: str
    sample_size_met: bool
    effect_met: bool
    significant: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "variable": self.variable,
            "n_control": self.n_control,
            "n_variant": self.n_variant,
            "control_mean": self.control_mean,
            "variant_mean": self.variant_mean,
            "control_std": self.control_std,
            "variant_std": self.variant_std,
            "cohens_d": self.cohens_d,
            "p_value": self.p_value,
            "winner": self.winner,
            "sample_size_met": self.sample_size_met,
            "effect_met": self.effect_met,
            "significant": self.significant,
        }


class ExperimentRepository:
    def __init__(self, database: DatabaseConnection | None = None) -> None:
        self.database = database

    def _get_database(self) -> DatabaseConnection:
        if self.database is None:
            self.database = DatabaseConnection()
        return self.database

    def create(
        self,
        name: str,
        description: str,
        hypothesis: str | None = None,
        variable: str | None = None,
        control_description: str | None = None,
        variant_description: str | None = None,
        min_effect: float | None = None,
        confidence_threshold: float | None = None,
    ) -> int:
        db = self._get_database()
        cursor = db.execute(
            "INSERT INTO experiments(name, description, started_at, status, hypothesis, variable, control_description, variant_description, min_effect, confidence_threshold) "
            "VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)",
            (
                name,
                description,
                utc_now_iso(),
                hypothesis,
                variable,
                control_description,
                variant_description,
                min_effect,
                confidence_threshold,
            ),
        )
        return cursor.lastrowid

    def get(self, experiment_id: int) -> Experiment:
        db = self._get_database()
        with db.cursor() as cursor:
            cursor.execute("SELECT * FROM experiments WHERE id = ?", (experiment_id,))
            row = cursor.fetchone()
        if row is None:
            raise KeyError(f"No experiment with id {experiment_id}")
        columns = [description[0] for description in cursor.description]
        return Experiment(**dict(zip(columns, row)))

    def list_active(self) -> list[Experiment]:
        db = self._get_database()
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT id, name, description, started_at, status, hypothesis, variable, control_description, variant_description, min_effect, confidence_threshold, ended_at "
                "FROM experiments WHERE status = 'active' ORDER BY id"
            )
            rows = cursor.fetchall()
        return [
            Experiment(
                id=int(row[0]),
                name=row[1],
                description=row[2],
                started_at=row[3],
                status=row[4],
                hypothesis=row[5],
                variable=row[6],
                control_description=row[7],
                variant_description=row[8],
                min_effect=row[9],
                confidence_threshold=row[10],
                ended_at=row[11],
            )
            for row in rows
        ]

    def assign_post(self, experiment_id: int, post_id: int, arm: str) -> int:
        if arm not in VALID_ARMS:
            raise ValueError(f"arm must be one of {VALID_ARMS}, got: {arm!r}")
        db = self._get_database()
        cursor = db.execute(
            "INSERT INTO experiment_posts(experiment_id, post_id, arm, assigned_at) VALUES (?, ?, ?, ?)",
            (experiment_id, post_id, arm, utc_now_iso()),
        )
        return cursor.lastrowid

    def posts_for_arm(self, experiment_id: int, arm: str) -> list[int]:
        db = self._get_database()
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT post_id FROM experiment_posts WHERE experiment_id = ? AND arm = ? ORDER BY post_id",
                (experiment_id, arm),
            )
            return [int(row[0]) for row in cursor.fetchall()]

    def complete(self, experiment_id: int) -> None:
        db = self._get_database()
        db.execute(
            "UPDATE experiments SET status = 'completed', ended_at = ? WHERE id = ?",
            (utc_now_iso(), experiment_id),
        )


def _latest_engagement_rates(db: DatabaseConnection, post_ids: list[int]) -> list[float]:
    if not post_ids:
        return []
    placeholders = ",".join("?" for _ in post_ids)
    with db.cursor() as cursor:
        cursor.execute(
            f"SELECT pm.post_id, pm.engagement_rate FROM post_metrics pm "
            f"WHERE pm.post_id IN ({placeholders}) AND pm.engagement_rate IS NOT NULL "
            f"AND pm.id = (SELECT MAX(pm2.id) FROM post_metrics pm2 "
            f"WHERE pm2.post_id = pm.post_id AND pm2.engagement_rate IS NOT NULL)",
            post_ids,
        )
        rates = [float(row[1]) for row in cursor.fetchall()]
    return rates


def compute_experiment_result(
    experiment_id: int,
    db: DatabaseConnection,
    min_sample_size: int = 10,
    min_effect: float = 0.15,
) -> ExperimentResult:
    repository = ExperimentRepository(db)
    experiment = repository.get(experiment_id)

    control_values = _latest_engagement_rates(db, repository.posts_for_arm(experiment_id, "control"))
    variant_values = _latest_engagement_rates(db, repository.posts_for_arm(experiment_id, "variant"))

    n_control = len(control_values)
    n_variant = len(variant_values)
    control_mean = statistics.mean(control_values)
    variant_mean = statistics.mean(variant_values)
    control_std = statistics.sample_stddev(control_values)
    variant_std = statistics.sample_stddev(variant_values)
    d = statistics.cohens_d(control_values, variant_values)
    p_value = statistics.two_sample_p_value(control_values, variant_values)

    sample_size_met = n_control >= min_sample_size and n_variant >= min_sample_size
    effect_met = abs(d) >= min_effect
    significant = sample_size_met and effect_met and p_value <= 0.05

    if significant and d > 0:
        winner = "variant"
    elif significant and d < 0:
        winner = "control"
    else:
        winner = "inconclusive"

    return ExperimentResult(
        experiment_id=experiment_id,
        variable=experiment.variable or "unknown",
        n_control=n_control,
        n_variant=n_variant,
        control_mean=control_mean,
        variant_mean=variant_mean,
        control_std=control_std,
        variant_std=variant_std,
        cohens_d=d,
        p_value=p_value,
        winner=winner,
        sample_size_met=sample_size_met,
        effect_met=effect_met,
        significant=significant,
    )
