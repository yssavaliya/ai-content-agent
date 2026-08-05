from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..settings import current_settings

MIGRATIONS_TABLE = "schema_migrations"

INITIAL_SCHEMA = [
    "CREATE TABLE IF NOT EXISTS posts ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT," 
    "external_id TEXT UNIQUE NOT NULL," 
    "caption TEXT NOT NULL," 
    "image_description TEXT NOT NULL," 
    "hashtags TEXT NOT NULL," 
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
    "status TEXT NOT NULL"
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

MIGRATIONS = [
    # In a production-ready system, future migration SQL statements are appended here.
]


class DatabaseConnection:
    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_path = current_settings().database_path
        self.db_path = Path(db_path)
        self.connection = sqlite3.connect(str(self.db_path), isolation_level=None)
        self.connection.execute("PRAGMA foreign_keys = ON")
        self._ensure_schema()

    @contextmanager
    def cursor(self) -> Iterator[sqlite3.Cursor]:
        cursor = self.connection.cursor()
        try:
            yield cursor
        finally:
            cursor.close()

    def execute(self, sql: str, parameters: tuple | None = None) -> sqlite3.Cursor:
        if parameters is None:
            return self.connection.execute(sql)
        return self.connection.execute(sql, parameters)

    def executemany(self, sql: str, seq_of_parameters: list[tuple]) -> sqlite3.Cursor:
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

    def _get_current_schema_version(self) -> int:
        with self.cursor() as cursor:
            cursor.execute("SELECT MAX(version) FROM schema_migrations")
            row = cursor.fetchone()
            return int(row[0]) if row and row[0] is not None else 0


def initialize_database(db_path: str | Path | None = None) -> None:
    DatabaseConnection(db_path=db_path).close()


def run_migrations(db_path: str | Path | None = None) -> None:
    db = DatabaseConnection(db_path=db_path)
    try:
        with db.connection:
            current_version = _get_current_schema_version(db)
            for index, migration in enumerate(MIGRATIONS, start=1):
                if index > current_version:
                    db.execute(migration)
                    db.execute(
                        "INSERT INTO schema_migrations(version) VALUES (?)",
                        (index,),
                    )
    finally:
        db.close()


def _get_current_schema_version(db: DatabaseConnection) -> int:
    with db.cursor() as cursor:
        cursor.execute(
            "SELECT MAX(version) FROM schema_migrations"
        )
        row = cursor.fetchone()
        return int(row[0]) if row and row[0] is not None else 0
