"""Transactional orchestration for Phase 01 video ingestion."""

from __future__ import annotations

from datetime import UTC, datetime
import json
import logging
from pathlib import Path
import subprocess
from typing import Any
from uuid import uuid4

from backend.config import canonical_json, config_hash
from backend.database.connection import bootstrap_database, database_connection
from backend.database.repository import insert_frame_batch, insert_run, insert_video, metadata_json, update_run_status
from backend.media import MediaError, TimestampAudit, inspect_video, iter_frames_with_pts, sha256_file


LOGGER = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def current_code_version(repository_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=repository_root, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def ingest_video(
    video_path: Path,
    config: dict[str, Any],
    *,
    repository_root: Path,
    parent_run_id: str | None = None,
    wall_clock_start: str | None = None,
) -> dict[str, Any]:
    """Persist one source video's metadata, PTS map, and reproducible root run."""
    suffixes = {suffix.lower() for suffix in config["input"]["supported_formats"]}
    if video_path.suffix.lower() not in suffixes:
        raise MediaError(f"Unsupported video format {video_path.suffix}; supported: {', '.join(sorted(suffixes))}")

    database_path = Path(config["paths"]["database_path"])
    if not database_path.is_absolute():
        database_path = repository_root / database_path
    schema_hash = bootstrap_database(database_path)
    metadata = inspect_video(video_path)
    video_id = str(uuid4())
    run_id = str(uuid4())
    source_sha256 = sha256_file(video_path)
    started_at = _utc_now()
    snapshot = canonical_json(config)
    audit = TimestampAudit()

    video_record = {
        "video_id": video_id,
        "filename": video_path.name,
        "path": str(video_path.resolve()),
        "sha256": source_sha256,
        "fps_nominal": metadata.fps_nominal,
        "width": metadata.width,
        "height": metadata.height,
        "duration_s": metadata.duration_s,
        "frame_count": metadata.frame_count,
        "variable_frame_rate": 0,
        "wall_clock_start": wall_clock_start or config["timestamp"].get("wall_clock_start"),
        "ingested_at": started_at,
        "metadata_json": metadata_json({"timestamp_audit": "pending_decode"}),
    }
    run_record = {
        "run_id": run_id,
        "parent_run_id": parent_run_id,
        "video_id": video_id,
        "model_version": None,
        "config_hash": config_hash(config),
        "config_json": snapshot,
        "schema_version": schema_hash,
        "code_version": current_code_version(repository_root),
        "source_video_sha256": source_sha256,
        "started_at": started_at,
        "status": "created",
        "notes": "Phase 01 ingestion run",
    }

    with database_connection(database_path) as connection:
        insert_video(connection, video_record)
        insert_run(connection, run_record)
        update_run_status(connection, run_id, "running")
    LOGGER.info("ingestion_started", extra={"run_id": run_id, "video_id": video_id, "video_path": str(video_path)})

    batch: list[tuple[int, float]] = []
    batch_size = config["streaming"]["frame_batch_size"]
    try:
        with database_connection(database_path) as connection:
            for frame_number, pts_s, frame_audit in iter_frames_with_pts(video_path):
                audit = frame_audit
                batch.append((frame_number, pts_s))
                if len(batch) >= batch_size:
                    insert_frame_batch(connection, video_id, batch)
                    batch.clear()
            if batch:
                insert_frame_batch(connection, video_id, batch)
            audit_data = audit.as_dict()
            connection.execute(
                """
                UPDATE videos
                SET frame_count = :frame_count,
                    variable_frame_rate = :variable_frame_rate,
                    metadata_json = :metadata_json
                WHERE video_id = :video_id
                """,
                {
                    "video_id": video_id,
                    "frame_count": audit.frame_count,
                    "variable_frame_rate": int(audit.variable_frame_rate),
                    "metadata_json": json.dumps({"timestamp_audit": audit_data}, sort_keys=True),
                },
            )
            update_run_status(connection, run_id, "completed", completed_at=_utc_now())
        LOGGER.info("ingestion_completed", extra={"run_id": run_id, "video_id": video_id, "video_path": str(video_path)})
    except Exception as error:
        with database_connection(database_path) as connection:
            update_run_status(connection, run_id, "failed", completed_at=_utc_now(), notes=str(error))
        LOGGER.exception("ingestion_failed", extra={"run_id": run_id, "video_id": video_id, "video_path": str(video_path)})
        raise

    return {
        "video_id": video_id,
        "run_id": run_id,
        "database_path": str(database_path),
        "timestamp_audit": audit.as_dict(),
    }
