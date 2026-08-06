from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, Sequence

from ..settings import current_settings

MIGRATIONS_TABLE = "schema_migrations"

INITIAL_SCHEMA = [
    "CREATE TABLE IF NOT EXISTS posts ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
    "external_id TEXT UNIQUE NOT NULL,"
    "caption TEXT NOT NULL,"
    "image_description TEXT NOT NULL,"
    "hashtags TEXT NOT NULL,"
    "topic TEXT,"
    "image_path TEXT,"
    "media_url TEXT,"
    "created_at TEXT NOT NULL"
    ")",
    "CREATE TABLE IF NOT EXISTS analytics ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
    "post_id INTEGER NOT NULL,"
    "impressions INTEGER NOT NULL,"
    "engagements INTEGER NOT NULL,"
    "collected_at TEXT NOT NULL,"
    "FOREIGN KEY(post_id) REFERENCES posts(id)"
    ")",
    "CREATE TABLE IF NOT EXISTS experiments ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
    "name TEXT UNIQUE NOT NULL,"
    "description TEXT NOT NULL,"
    "started_at TEXT NOT NULL,"
    "status TEXT NOT NULL,"
    "hypothesis TEXT,"
    "variable TEXT,"
    "control_description TEXT,"
    "variant_description TEXT,"
    "min_effect REAL,"
    "confidence_threshold REAL,"
    "ended_at TEXT"
    ")",
    "CREATE TABLE IF NOT EXISTS research_raw ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
    "provider TEXT NOT NULL,"
    "title TEXT NOT NULL,"
    "source TEXT NOT NULL,"
    "summary TEXT NOT NULL,"
    "category TEXT NOT NULL,"
    "url TEXT,"
    "retrieved_at TEXT NOT NULL,"
    "normalized_at TEXT NOT NULL,"
    "raw_payload TEXT NOT NULL"
    ")",
    "CREATE TABLE IF NOT EXISTS planner_ideas ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
    "research_id INTEGER NOT NULL,"
    "idea_text TEXT NOT NULL,"
    "educational_score REAL NOT NULL,"
    "originality_score REAL NOT NULL,"
    "engagement_score REAL NOT NULL,"
    "relevance_score REAL NOT NULL,"
    "total_score REAL NOT NULL,"
    "selected INTEGER NOT NULL,"
    "reasoning TEXT NOT NULL,"
    "created_at TEXT NOT NULL,"
    "FOREIGN KEY(research_id) REFERENCES research_raw(id)"
    ")",
    "CREATE TABLE IF NOT EXISTS creator_outputs ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
    "planner_id INTEGER NOT NULL,"
    "carousel_outline TEXT NOT NULL,"
    "caption TEXT NOT NULL,"
    "cta TEXT NOT NULL,"
    "hashtags TEXT NOT NULL,"
    "image_prompt TEXT NOT NULL,"
    "alt_text TEXT NOT NULL,"
    "markdown_path TEXT NOT NULL,"
    "json_path TEXT NOT NULL,"
    "created_at TEXT NOT NULL,"
    "FOREIGN KEY(planner_id) REFERENCES planner_ideas(id)"
    ")",
    "CREATE TABLE IF NOT EXISTS review_history ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
    "creator_output_id INTEGER NOT NULL,"
    "status TEXT NOT NULL,"
    "feedback TEXT NOT NULL,"
    "timestamp TEXT NOT NULL,"
    "FOREIGN KEY(creator_output_id) REFERENCES creator_outputs(id)"
    ")",
    "CREATE TABLE IF NOT EXISTS image_assets ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
    "creator_output_id INTEGER NOT NULL,"
    "provider TEXT NOT NULL,"
    "prompt TEXT NOT NULL,"
    "file_path TEXT NOT NULL,"
    "metadata TEXT NOT NULL,"
    "created_at TEXT NOT NULL,"
    "FOREIGN KEY(creator_output_id) REFERENCES creator_outputs(id)"
    ")",
    "CREATE TABLE IF NOT EXISTS publish_packages ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
    "creator_output_id INTEGER NOT NULL,"
    "status TEXT NOT NULL,"
    "published_id TEXT NOT NULL,"
    "package_path TEXT NOT NULL,"
    "metadata TEXT NOT NULL,"
    "created_at TEXT NOT NULL,"
    "FOREIGN KEY(creator_output_id) REFERENCES creator_outputs(id)"
    ")",
]

V1_TABLES = [
    "CREATE TABLE IF NOT EXISTS post_metrics ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
    "post_id INTEGER NOT NULL,"
    "media_id TEXT,"
    "impressions INTEGER,"
    "reach INTEGER,"
    "likes INTEGER,"
    "comments INTEGER,"
    "shares INTEGER,"
    "saves INTEGER,"
    "engagement INTEGER,"
    "engagement_rate REAL,"
    "collected_at TEXT NOT NULL,"
    "raw_payload TEXT NOT NULL,"
    "FOREIGN KEY(post_id) REFERENCES posts(id)"
    ")",
    "CREATE TABLE IF NOT EXISTS observations ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
    "collected_at TEXT NOT NULL,"
    "source TEXT NOT NULL,"
    "post_id INTEGER,"
    "metric_name TEXT NOT NULL,"
    "metric_value REAL,"
    "metadata TEXT NOT NULL,"
    "FOREIGN KEY(post_id) REFERENCES posts(id)"
    ")",
    "CREATE TABLE IF NOT EXISTS experiment_posts ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
    "experiment_id INTEGER NOT NULL,"
    "post_id INTEGER NOT NULL,"
    "arm TEXT NOT NULL,"
    "assigned_at TEXT NOT NULL,"
    "UNIQUE(experiment_id, post_id),"
    "FOREIGN KEY(experiment_id) REFERENCES experiments(id),"
    "FOREIGN KEY(post_id) REFERENCES posts(id)"
    ")",
    "CREATE TABLE IF NOT EXISTS strategy_history ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT,"
    "applied_at TEXT NOT NULL,"
    "trigger TEXT NOT NULL,"
    "recommendation_id INTEGER,"
    "previous_text TEXT NOT NULL,"
    "new_text TEXT NOT NULL,"
    "notes TEXT NOT NULL"
    ")",
]


def _ensure_column(db: "DatabaseConnection", table: str, column: str, coltype: str) -> None:
    with db.cursor() as cursor:
        cursor.execute(f"PRAGMA table_info({table})")
        existing = {row[1] for row in cursor.fetchall()}
    if column not in existing:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")


def _migration_v1(db: "DatabaseConnection") -> None:
    for statement in V1_TABLES:
        db.execute(statement)
    _ensure_column(db, "posts", "topic", "TEXT")
    _ensure_column(db, "posts", "image_path", "TEXT")
    _ensure_column(db, "posts", "media_url", "TEXT")
    _ensure_column(db, "experiments", "hypothesis", "TEXT")
    _ensure_column(db, "experiments", "variable", "TEXT")
    _ensure_column(db, "experiments", "control_description", "TEXT")
    _ensure_column(db, "experiments", "variant_description", "TEXT")
    _ensure_column(db, "experiments", "min_effect", "REAL")
    _ensure_column(db, "experiments", "confidence_threshold", "REAL")
    _ensure_column(db, "experiments", "ended_at", "TEXT")


Migration = str | Callable[["DatabaseConnection"], None]

MIGRATIONS: list[Migration] = [
    _migration_v1,
]


class DatabaseConnection:
    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_path = current_settings().database_path
        self.db_path = Path(db_path)
        self.connection = sqlite3.connect(str(self.db_path), isolation_level=None)
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._ensure_schema()
        run_migrations(db=self)

    @contextmanager
    def cursor(self) -> Iterator[sqlite3.Cursor]:
        cursor = self.connection.cursor()
        try:
            yield cursor
        finally:
            cursor.close()

    @contextmanager
    def transaction(self) -> Iterator["DatabaseConnection"]:
        """Run statements in an explicit transaction with rollback on error.

        The connection uses autocommit mode (isolation_level=None), so a plain
        ``with self.connection:`` block would not provide atomicity.
        """
        self.connection.execute("BEGIN")
        try:
            yield self
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        else:
            self.connection.execute("COMMIT")

    def execute(self, sql: str, parameters: tuple | None = None) -> sqlite3.Cursor:
        if parameters is None:
            return self.connection.execute(sql)
        return self.connection.execute(sql, parameters)

    def executemany(self, sql: str, seq_of_parameters: Sequence[tuple]) -> sqlite3.Cursor:
        return self.connection.executemany(sql, seq_of_parameters)

    def close(self) -> None:
        self.connection.close()

    def _ensure_schema(self) -> None:
        with self.connection:
            for statement in INITIAL_SCHEMA:
                self.connection.execute(statement)
            self.connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)"
            )
            self.connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version) VALUES (0)"
            )


def initialize_database(db_path: str | Path | None = None) -> None:
    DatabaseConnection(db_path=db_path).close()


def _get_current_schema_version(db: DatabaseConnection) -> int:
    with db.cursor() as cursor:
        cursor.execute("SELECT MAX(version) FROM schema_migrations")
        row = cursor.fetchone()
        return int(row[0]) if row and row[0] is not None else 0


def run_migrations(db_path: str | Path | None = None, db: DatabaseConnection | None = None) -> None:
    owns_db = db is None
    if db is None:
        db = DatabaseConnection(db_path=db_path)
    try:
        current_version = _get_current_schema_version(db)
        for index, migration in enumerate(MIGRATIONS, start=1):
            if index > current_version:
                if callable(migration):
                    migration(db)
                else:
                    db.execute(migration)
                db.execute(
                    "INSERT INTO schema_migrations(version) VALUES (?)",
                    (index,),
                )
    finally:
        if owns_db:
            db.close()
