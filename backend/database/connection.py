"""Canonical SQLite bootstrap with per-connection integrity enforcement."""

from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
import sqlite3
from typing import Iterator
from datetime import UTC, datetime


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPOSITORY_ROOT / "backend" / "database" / "schema.sql"


class SchemaMigrationRequired(RuntimeError):
    """Raised when an existing database is not known to match this schema."""


def schema_version() -> str:
    """Identify the exact schema text used for a processing run."""
    return sha256(SCHEMA_PATH.read_bytes()).hexdigest()


def connect(database_path: Path) -> sqlite3.Connection:
    """Open one SQLite connection with foreign keys enabled for this connection."""
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        connection.close()
        raise RuntimeError("SQLite foreign-key enforcement could not be enabled")
    return connection


def bootstrap_database(database_path: Path) -> str:
    """Bootstrap a new database or confirm a previously recorded schema version."""
    version = schema_version()
    with connect(database_path) as connection:
        existing_tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")
        }
        if existing_tables and "schema_migrations" not in existing_tables:
            raise SchemaMigrationRequired(
                "Existing database has no schema migration record; explicitly migrate it or use a disposable database"
            )
        if "schema_migrations" in existing_tables:
            known_versions = {row[0] for row in connection.execute("SELECT schema_version FROM schema_migrations")}
            if known_versions and version not in known_versions:
                raise SchemaMigrationRequired(
                    "Existing database was created from a different schema; explicitly migrate it before use"
                )
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations (schema_version, applied_at) VALUES (?, ?)",
            (version, datetime.now(UTC).isoformat()),
        )
        connection.commit()
    return version


def migrate_database(database_path: Path) -> str:
    """Explicitly upgrade an existing database to the current canonical schema version."""
    version = schema_version()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(database_path) as connection:
        existing_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (schema_version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )

        # Check and migrate columns in crossing_events
        if "crossing_events" in existing_tables:
            cols = {row[1] for row in connection.execute("PRAGMA table_info(crossing_events)")}
            if "deduplicated" not in cols:
                connection.execute("ALTER TABLE crossing_events ADD COLUMN deduplicated INTEGER NOT NULL DEFAULT 0")

        # Check and migrate columns in traffic_volume_bins
        if "traffic_volume_bins" in existing_tables:
            cols = {row[1] for row in connection.execute("PRAGMA table_info(traffic_volume_bins)")}
            if "observed_duration_s" not in cols:
                connection.execute("ALTER TABLE traffic_volume_bins ADD COLUMN observed_duration_s REAL")

        # Execute full schema to create any new tables (e.g. video_segments) and indexes
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        connection.execute(
            "INSERT OR IGNORE INTO schema_migrations (schema_version, applied_at) VALUES (?, ?)",
            (version, datetime.now(UTC).isoformat()),
        )
        connection.commit()
    return version



@contextmanager
def database_connection(database_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(database_path)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
