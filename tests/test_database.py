from pathlib import Path
import sqlite3

import pytest

from backend.database.connection import SchemaMigrationRequired, bootstrap_database, connect, database_connection


def test_bootstrap_enables_foreign_keys_on_every_connection(tmp_path: Path) -> None:
    database_path = tmp_path / "traffic.sqlite3"
    bootstrap_database(database_path)
    with connect(database_path) as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO processing_runs (
                    run_id, video_id, config_hash, config_json, schema_version,
                    code_version, source_video_sha256, started_at, status
                ) VALUES ('orphan-run', 'missing-video', 'config', '{}', 'schema', 'code', 'sha', 'now', 'created')
                """
            )


def test_bootstrap_is_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "traffic.sqlite3"
    assert bootstrap_database(database_path) == bootstrap_database(database_path)
    with database_connection(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 1


def test_bootstrap_rejects_a_database_with_an_unknown_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE legacy_table (id INTEGER PRIMARY KEY)")
    with pytest.raises(SchemaMigrationRequired):
        bootstrap_database(database_path)
