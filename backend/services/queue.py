"""Phase 09 stopped vehicle and calibrated queue detection service orchestration.

Coordinates queue detection runs derived from tracking or speed parent runs,
validates accepted calibration provenance, persists observations to canonical
stop_events and queue_events tables, and computes summary statistics.
Operates independently of signal phase timing.
"""

from __future__ import annotations

import logging
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

from backend.config import canonical_json, config_hash
from backend.database.connection import database_connection, schema_version
from backend.database.repository import (
    fetch_calibration_run_by_id,
    fetch_counting_lines_for_video,
    fetch_latest_accepted_calibration,
    fetch_queue_detection_stats,
    fetch_queue_events_for_run,
    fetch_run_by_id,
    fetch_speed_observations_for_run,
    fetch_stop_events_for_run,
    fetch_tracks_for_run,
    fetch_zones_for_video,
    insert_queue_events,
    insert_run,
    insert_stop_events,
    update_run_status,
)
from backend.queue import evaluate_queue_events_for_run
from backend.services.calibration import get_calibration
from backend.services.ingestion import _utc_now, current_code_version
from backend.speed import estimate_speeds_for_trajectories
from backend.trajectories import build_trajectories

logger = logging.getLogger(__name__)


def run_queue_detection(
    parent_run_id: str,
    calibration_id: str | None = None,
    config: dict[str, Any] | None = None,
    repository_root: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Execute stopped vehicle and queue detection for a completed parent run.

    Parameters:
        parent_run_id: UUID of an existing completed tracking or speed processing run.
        calibration_id: Optional UUID of an accepted calibration run. If None,
                        the latest accepted calibration for the video is used.
        config: Loaded project configuration.
        repository_root: Path to repository root.
        connection: Optional existing SQLite database connection.

    Returns:
        Summary dict containing run_id, parent_run_id, calibration_id,
        stop_event_count, queue_event_count, and statistics.

    Raises:
        ValueError: If parent run does not exist or is not completed,
                    or if an unaccepted calibration is provided.
    """
    if config is None:
        raise ValueError("config must be provided")

    repo_root = repository_root or Path(__file__).resolve().parents[2]
    database_path = Path(config["paths"]["database_path"])
    if not database_path.is_absolute():
        database_path = repo_root / database_path

    run_id = str(uuid4())

    def _execute(conn: sqlite3.Connection) -> dict[str, Any]:
        parent = fetch_run_by_id(conn, parent_run_id)
        if parent is None:
            raise ValueError(f"Parent processing run does not exist: {parent_run_id}")
        if parent["status"] != "completed":
            raise ValueError(f"Parent processing run is not completed (status={parent['status']})")

        video_id = str(parent["video_id"])
        video = conn.execute(
            "SELECT video_id, width, height, duration_s, frame_count FROM videos WHERE video_id = ?",
            (video_id,),
        ).fetchone()
        if video is None:
            raise ValueError(f"Video {video_id} referenced by parent run does not exist")

        v_width = int(video["width"]) if video["width"] is not None else None
        v_height = int(video["height"]) if video["height"] is not None else None
        last_frame = int(video["frame_count"] - 1) if video["frame_count"] is not None else None

        # Resolve calibration
        resolved_calibration_id: str | None = None
        homography_matrix = None
        if calibration_id is not None:
            calib_row = fetch_calibration_run_by_id(conn, calibration_id)
            if calib_row is None:
                raise ValueError(f"Calibration run '{calibration_id}' not found")
            if int(calib_row["accepted"]) != 1:
                raise ValueError(
                    f"Calibration run '{calibration_id}' is not accepted (accepted=0); "
                    "queue detection rejects unaccepted calibration"
                )
            resolved_calibration_id = calibration_id
            calib_details = get_calibration(resolved_calibration_id, connection=conn)
            if calib_details and "parameters" in calib_details:
                homography_matrix = calib_details["parameters"].get("homography_matrix")
        else:
            latest_calib = fetch_latest_accepted_calibration(conn, video_id)
            if latest_calib is not None:
                resolved_calibration_id = str(latest_calib["calibration_id"])
                calib_details = get_calibration(resolved_calibration_id, connection=conn)
                if calib_details and "parameters" in calib_details:
                    homography_matrix = calib_details["parameters"].get("homography_matrix")

        # Create child processing run record
        now_ts = _utc_now()
        insert_run(
            conn,
            {
                "run_id": run_id,
                "parent_run_id": parent_run_id,
                "video_id": video_id,
                "model_version": parent["model_version"],
                "config_hash": config_hash(config),
                "config_json": canonical_json(config),
                "schema_version": schema_version(),
                "code_version": current_code_version(repo_root),
                "source_video_sha256": parent["source_video_sha256"],
                "started_at": now_ts,
                "status": "running",
                "notes": f"Phase 09 queue detection run (parent={parent_run_id})",
            },
        )
        conn.commit()

        try:
            # Check if parent run already has speed observations
            existing_speed_obs = fetch_speed_observations_for_run(conn, parent_run_id)
            if existing_speed_obs:
                # Parent run is a speed estimation run
                tracking_run_id = parent["parent_run_id"] or parent_run_id
                tracks_raw = fetch_tracks_for_run(conn, tracking_run_id)
                trajectories = build_trajectories(
                    observations=tracks_raw,
                    video_width=v_width,
                    video_height=v_height,
                    last_video_frame=last_frame,
                    config=config,
                )
                speed_observations = [dict(r) for r in existing_speed_obs]
            else:
                # Parent run is a tracking run
                tracks_raw = fetch_tracks_for_run(conn, parent_run_id)
                trajectories = build_trajectories(
                    observations=tracks_raw,
                    video_width=v_width,
                    video_height=v_height,
                    last_video_frame=last_frame,
                    config=config,
                )
                if homography_matrix is not None and resolved_calibration_id is not None:
                    traj_speeds = estimate_speeds_for_trajectories(
                        trajectories=trajectories,
                        homography_matrix=homography_matrix,
                        calibration_id=resolved_calibration_id,
                        run_id=run_id,
                        config=config,
                    )
                    speed_observations = [
                        obs.to_dict()
                        for obs_list in traj_speeds.values()
                        for obs in obs_list
                    ]
                else:
                    speed_observations = []

            # Fetch zones and counting lines for spatial containment
            zones = fetch_zones_for_video(conn, video_id)
            counting_lines = fetch_counting_lines_for_video(conn, video_id)

            # Evaluate stop events and queue events
            stop_events, queue_events = evaluate_queue_events_for_run(
                speed_observations=speed_observations,
                trajectories=trajectories,
                zones=zones,
                counting_lines=counting_lines,
                homography_matrix=homography_matrix,
                config=config,
                run_id=run_id,
                video_id=video_id,
            )

            # Persist stop events and queue events to database
            if stop_events:
                insert_stop_events(conn, [se.to_dict() for se in stop_events])
            if queue_events:
                insert_queue_events(conn, [qe.to_dict() for qe in queue_events])

            # Mark run as completed
            completed_ts = _utc_now()
            update_run_status(conn, run_id, "completed", completed_at=completed_ts)
            conn.commit()

            stats = fetch_queue_detection_stats(conn, run_id)

            return {
                "run_id": run_id,
                "parent_run_id": parent_run_id,
                "calibration_id": resolved_calibration_id,
                "video_id": video_id,
                "stop_event_count": len(stop_events),
                "queue_event_count": len(queue_events),
                "stats": stats,
            }

        except Exception as err:
            update_run_status(conn, run_id, "failed", completed_at=_utc_now(), notes=str(err))
            conn.commit()
            raise

    if connection is not None:
        return _execute(connection)

    with database_connection(database_path) as conn:
        return _execute(conn)


def get_queue_summary(
    run_id: str,
    config: dict[str, Any] | None = None,
    repository_root: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Retrieve queue detection summary statistics for a run."""
    def _query(conn: sqlite3.Connection) -> dict[str, Any]:
        stats = fetch_queue_detection_stats(conn, run_id)
        return {
            "run_id": run_id,
            "stats": stats,
        }

    if connection is not None:
        return _query(connection)

    if config is not None:
        repo_root = repository_root or Path(__file__).resolve().parents[2]
        database_path = Path(config["paths"]["database_path"])
        if not database_path.is_absolute():
            database_path = repo_root / database_path
        with database_connection(database_path) as conn:
            return _query(conn)

    raise ValueError("Either an open database connection or config must be provided")


def get_stop_events(
    run_id: str,
    track_id: int | None = None,
    limit: int | None = None,
    config: dict[str, Any] | None = None,
    repository_root: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Retrieve stop events for a queue detection run, optionally filtered by track."""
    def _query(conn: sqlite3.Connection) -> dict[str, Any]:
        rows = fetch_stop_events_for_run(conn, run_id, track_id=track_id)
        if limit is not None and limit > 0:
            rows = rows[:limit]
        return {
            "run_id": run_id,
            "track_id": track_id,
            "count": len(rows),
            "stop_events": [dict(r) for r in rows],
        }

    if connection is not None:
        return _query(connection)

    if config is not None:
        repo_root = repository_root or Path(__file__).resolve().parents[2]
        database_path = Path(config["paths"]["database_path"])
        if not database_path.is_absolute():
            database_path = repo_root / database_path
        with database_connection(database_path) as conn:
            return _query(conn)

    raise ValueError("Either an open database connection or config must be provided")


def get_queue_events(
    run_id: str,
    zone_id: str | None = None,
    approach: str | None = None,
    limit: int | None = None,
    config: dict[str, Any] | None = None,
    repository_root: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Retrieve queue events for a queue detection run, optionally filtered by zone/approach."""
    def _query(conn: sqlite3.Connection) -> dict[str, Any]:
        rows = fetch_queue_events_for_run(conn, run_id, zone_id=zone_id, approach=approach)
        if limit is not None and limit > 0:
            rows = rows[:limit]
        return {
            "run_id": run_id,
            "zone_id": zone_id,
            "approach": approach,
            "count": len(rows),
            "queue_events": [dict(r) for r in rows],
        }

    if connection is not None:
        return _query(connection)

    if config is not None:
        repo_root = repository_root or Path(__file__).resolve().parents[2]
        database_path = Path(config["paths"]["database_path"])
        if not database_path.is_absolute():
            database_path = repo_root / database_path
        with database_connection(database_path) as conn:
            return _query(conn)

    raise ValueError("Either an open database connection or config must be provided")
