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


def insert_model_version(connection: sqlite3.Connection, model: dict[str, object]) -> None:
    connection.execute(
        """
        INSERT OR IGNORE INTO model_versions (model_version, model_path, sha256, dataset_version, created_at, metrics_json)
        VALUES (:model_version, :model_path, :sha256, :dataset_version, :created_at, :metrics_json)
        """,
        model,
    )


def insert_detections(connection: sqlite3.Connection, rows: Iterable[dict[str, object]]) -> None:
    connection.executemany(
        """
        INSERT INTO detections (
            detection_id, run_id, video_id, frame_number, timestamp_s, class_id, class_name,
            confidence, x1, y1, x2, y2, ground_x, ground_y, width_px, height_px
        ) VALUES (
            :detection_id, :run_id, :video_id, :frame_number, :timestamp_s, :class_id, :class_name,
            :confidence, :x1, :y1, :x2, :y2, :ground_x, :ground_y, :width_px, :height_px
        )
        """,
        rows,
    )


def insert_tracks(connection: sqlite3.Connection, rows: Iterable[dict[str, object]]) -> None:
    connection.executemany(
        """
        INSERT INTO tracks (
            track_observation_id, run_id, video_id, track_id, frame_number, timestamp_s,
            vehicle_class, confidence, x1, y1, x2, y2, ground_x, ground_y,
            world_x, world_y, calibration_id, trajectory_status
        ) VALUES (
            :track_observation_id, :run_id, :video_id, :track_id, :frame_number, :timestamp_s,
            :vehicle_class, :confidence, :x1, :y1, :x2, :y2, :ground_x, :ground_y,
            :world_x, :world_y, :calibration_id, :trajectory_status
        )
        """,
        rows,
    )


def fetch_detections_for_tracking(connection: sqlite3.Connection, run_id: str) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT detection_id, run_id, video_id, frame_number, timestamp_s,
               class_id, class_name, confidence, x1, y1, x2, y2, ground_x, ground_y
        FROM detections
        WHERE run_id = ?
        ORDER BY frame_number ASC, confidence DESC
        """,
        (run_id,),
    ).fetchall()

