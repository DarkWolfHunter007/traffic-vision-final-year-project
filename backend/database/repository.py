"""Phase 01 persistence operations using the canonical schema."""

from __future__ import annotations

import json
import sqlite3
from typing import Iterable


def insert_video(connection: sqlite3.Connection, video: dict[str, object]) -> None:
    connection.execute(
        """
        INSERT INTO videos (
            video_id, filename, path, sha256, fps_nominal, width, height,
            duration_s, frame_count, variable_frame_rate, wall_clock_start,
            ingested_at, metadata_json
        ) VALUES (
            :video_id, :filename, :path, :sha256, :fps_nominal, :width, :height,
            :duration_s, :frame_count, :variable_frame_rate, :wall_clock_start,
            :ingested_at, :metadata_json
        )
        """,
        video,
    )


def insert_run(connection: sqlite3.Connection, run: dict[str, object]) -> None:
    connection.execute(
        """
        INSERT INTO processing_runs (
            run_id, parent_run_id, video_id, model_version, config_hash,
            config_json, schema_version, code_version, source_video_sha256,
            started_at, status, notes
        ) VALUES (
            :run_id, :parent_run_id, :video_id, :model_version, :config_hash,
            :config_json, :schema_version, :code_version, :source_video_sha256,
            :started_at, :status, :notes
        )
        """,
        run,
    )


def update_run_status(
    connection: sqlite3.Connection, run_id: str, status: str, completed_at: str | None = None, notes: str | None = None
) -> None:
    connection.execute(
        """
        UPDATE processing_runs
        SET status = :status, completed_at = :completed_at, notes = COALESCE(:notes, notes)
        WHERE run_id = :run_id
        """,
        {"run_id": run_id, "status": status, "completed_at": completed_at, "notes": notes},
    )


def insert_frame_batch(connection: sqlite3.Connection, video_id: str, frames: Iterable[tuple[int, float]]) -> None:
    connection.executemany(
        "INSERT INTO video_frames (video_id, frame_number, pts_s) VALUES (?, ?, ?)",
        ((video_id, frame_number, pts_s) for frame_number, pts_s in frames),
    )


def metadata_json(metadata: dict[str, object]) -> str:
    return json.dumps(metadata, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
