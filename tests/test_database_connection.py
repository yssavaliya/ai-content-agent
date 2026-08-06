import sqlite3
import tempfile
import unittest
from pathlib import Path

from ai_content_agent.database.connection import (
    DatabaseConnection,
    initialize_database,
    run_migrations,
    MIGRATIONS_TABLE,
)


class DatabaseConnectionTests(unittest.TestCase):
    def test_initialize_database_creates_expected_tables(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "agent.db"
            initialize_database(db_path)

            connection = sqlite3.connect(db_path)
            try:
                cursor = connection.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = {row[0] for row in cursor.fetchall()}
                self.assertIn("posts", tables)
                self.assertIn("analytics", tables)
                self.assertIn("experiments", tables)
                self.assertIn(MIGRATIONS_TABLE, tables)
            finally:
                connection.close()

    def test_database_connection_supports_query_execution(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "agent.db"
            initialize_database(db_path)

            db = DatabaseConnection(db_path)
            try:
                db.execute(
                    "INSERT INTO posts(external_id, caption, image_description, hashtags, created_at) VALUES (?, ?, ?, ?, ?)",
                    ("post-123", "caption", "description", "#tag", "2026-08-05T00:00:00Z"),
                )
                result = db.execute("SELECT external_id, caption FROM posts WHERE external_id = ?", ("post-123",))
                row = result.fetchone()
                self.assertEqual(row, ("post-123", "caption"))
            finally:
                db.close()

    def test_run_migrations_applies_and_preserves_schema_version(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "agent.db"
            initialize_database(db_path)

            connection = sqlite3.connect(db_path)
            try:
                cursor = connection.cursor()
                cursor.execute(f"SELECT MAX(version) FROM {MIGRATIONS_TABLE}")
                row = cursor.fetchone()
                self.assertEqual(row[0], 1)

                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('post_metrics', 'observations', 'experiment_posts', 'strategy_history')")
                tables = {row[0] for row in cursor.fetchall()}
                self.assertEqual(tables, {"post_metrics", "observations", "experiment_posts", "strategy_history"})
            finally:
                connection.close()

            run_migrations(db_path)

            connection = sqlite3.connect(db_path)
            try:
                cursor = connection.cursor()
                cursor.execute(f"SELECT MAX(version) FROM {MIGRATIONS_TABLE}")
                row = cursor.fetchone()
                self.assertEqual(row[0], 1)
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
