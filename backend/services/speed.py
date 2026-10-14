"""Phase 08 calibrated speed estimation service orchestration.

Coordinates speed estimation runs derived from tracking parent runs,
validates accepted calibration provenance, persists observations to
canonical speed_observations table, and computes summary statistics.
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
    fetch_latest_accepted_calibration,
    fetch_run_by_id,
    fetch_speed_observation_stats,
    fetch_speed_observations_for_run,
    fetch_tracks_for_run,
    insert_run,
    insert_speed_observations,
    update_run_status,
)
from backend.services.calibration import get_calibration
from backend.services.ingestion import _utc_now, current_code_version
from backend.speed import estimate_speeds_for_trajectories
from backend.trajectories import build_trajectories

logger = logging.getLogger(__name__)


def run_speed_estimation(
    parent_run_id: str,
    calibration_id: str | None = None,
    config: dict[str, Any] | None = None,
    repository_root: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Execute calibrated speed estimation for a completed tracking parent run.

    Parameters:
        parent_run_id: UUID of an existing completed tracking processing run.
        calibration_id: Optional UUID of an accepted calibration run. If None,
                        the latest accepted calibration for the video is used.
        config: Loaded project configuration.
        repository_root: Path to repository root.
        connection: Optional existing SQLite database connection.

    Transaction semantics: the service commits its own run rows. On a
    caller-supplied ``connection`` it therefore also commits the caller's
    pending transaction (on success and on failure); only the service's own
    speed_observations inserts are rolled back on failure (via a SAVEPOINT),
    after which the run is marked 'failed'.

    Returns:
        Summary dict containing run_id, parent_run_id, calibration_id,
        observation counts, and speed statistics.

    Raises:
        ValueError: If parent run does not exist/not completed, or if calibration
                    is missing, rejected, or invalid.
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
            raise ValueError(f"Parent tracking run is not completed (status={parent['status']})")

        has_tracks = conn.execute(
            "SELECT 1 FROM tracks WHERE run_id = ? LIMIT 1", (parent_run_id,)
        ).fetchone()
        is_tracking_note = str(parent["notes"] or "").startswith("Phase 03 ByteTrack")
        if has_tracks is None and not is_tracking_note:
            raise ValueError(
                f"Parent run {parent_run_id} is not a tracking run (no track observations); "
                "speed estimation requires a completed tracking parent run"
            )

        video_id = str(parent["video_id"])
        video = conn.execute(
            "SELECT video_id, width, height, duration_s, frame_count FROM videos WHERE video_id = ?",
            (video_id,),
        ).fetchone()
        if video is None:
            raise ValueError(f"Video {video_id} referenced by parent run does not exist")

        v_width = int(video["width"]) if video["width"] is not None else None
        v_height = int(video["height"]) if video["height"] is not None else None
        v_duration = float(video["duration_s"]) if video["duration_s"] is not None else None
        last_frame = int(video["frame_count"] - 1) if video["frame_count"] is not None else None

        # Resolve calibration
        resolved_calibration_id: str
        if calibration_id is not None:
            calib_row = fetch_calibration_run_by_id(conn, calibration_id)
            if calib_row is None:
                raise ValueError(f"Calibration run '{calibration_id}' not found")
            if str(calib_row["video_id"]) != video_id:
                raise ValueError(
                    f"Calibration run '{calibration_id}' belongs to video '{calib_row['video_id']}', "
                    f"not the parent run's video '{video_id}'"
                )
            if int(calib_row["accepted"]) != 1:
                raise ValueError(
                    f"Calibration run '{calibration_id}' is not accepted (accepted=0); "
                    "physical speed estimation is unavailable until calibration is accepted"
                )
            resolved_calibration_id = calibration_id
        else:
            latest_calib = fetch_latest_accepted_calibration(conn, video_id)
            if latest_calib is None:
                raise ValueError(
                    f"No accepted calibration found for video '{video_id}'; "
                    "physical speed estimation is unavailable until calibration is accepted"
                )
            resolved_calibration_id = str(latest_calib["calibration_id"])

        # Fetch calibration details and homography matrix
        calib_details = get_calibration(resolved_calibration_id, connection=conn)
        if calib_details is None or "parameters" not in calib_details:
            raise ValueError(f"Failed to load parameters for calibration '{resolved_calibration_id}'")

        homography_matrix = calib_details["parameters"].get("homography_matrix")
        if homography_matrix is None:
            raise ValueError(f"Calibration '{resolved_calibration_id}' does not contain homography_matrix")

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
                "notes": f"Phase 08 calibrated speed estimation run using calibration {resolved_calibration_id}",
            },
        )
        conn.commit()

        savepoint = "speed_insert_" + uuid4().hex
        conn.execute(f"SAVEPOINT {savepoint}")
        try:
            # Fetch tracks and reconstruct trajectories
            tracks_raw = fetch_tracks_for_run(conn, parent_run_id)
            trajectories = build_trajectories(
                observations=tracks_raw,
                video_width=v_width,
                video_height=v_height,
                last_video_frame=last_frame,
                config=config,
            )

            # Estimate speeds across trajectories
            trajectory_speeds = estimate_speeds_for_trajectories(
                trajectories=trajectories,
                homography_matrix=homography_matrix,
                calibration_id=resolved_calibration_id,
                run_id=run_id,
                config=config,
            )

            # Collect all observation dictionaries
            all_rows: list[dict[str, Any]] = []
            for track_id, obs_list in sorted(trajectory_speeds.items()):
                for obs in obs_list:
                    all_rows.append(obs.to_dict())

            # Batch insert into speed_observations
            insert_speed_observations(conn, all_rows)

            # Completion status and stats are produced inside the savepoint so
            # that any failure here rolls back the inserted rows too.
            completed_ts = _utc_now()
            update_run_status(conn, run_id, "completed", completed_at=completed_ts)
            stats = fetch_speed_observation_stats(conn, run_id)
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            conn.commit()

            return {
                "run_id": run_id,
                "parent_run_id": parent_run_id,
                "calibration_id": resolved_calibration_id,
                "video_id": video_id,
                "trajectory_count": len(trajectories),
                "total_observations": stats["total_count"],
                "valid_count": stats["valid_count"],
                "unavailable_count": stats["unavailable_count"],
                "invalid_count": stats["invalid_count"],
                "mean_speed_kmh": stats["mean_speed_kmh"],
                "max_speed_kmh": stats["max_speed_kmh"],
                "mean_speed_mps": stats["mean_speed_mps"],
                "max_speed_mps": stats["max_speed_mps"],
            }

        except Exception as err:
            # Undo only this service's inserts. Any caller pending work was
            # already committed at entry, so it is not affected.
            try:
                conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            except sqlite3.Error:
                if owns_connection:
                    conn.rollback()
            update_run_status(conn, run_id, "failed", completed_at=_utc_now(), notes=str(err))
            conn.commit()
            raise

    if connection is not None:
        owns_connection = False
        return _execute(connection)

    owns_connection = True
    with database_connection(database_path) as conn:
        return _execute(conn)


def get_speed_observations(
    run_id: str,
    track_id: int | None = None,
    limit: int | None = None,
    config: dict[str, Any] | None = None,
    repository_root: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Retrieve speed observations and summary metrics for a speed run.

    Parameters:
        run_id: UUID of speed estimation processing run.
        track_id: Optional filter for a specific vehicle track ID.
        limit: Optional maximum number of observation records to return.
        config: Optional project configuration.
        repository_root: Optional repository root path.
        connection: Optional database connection.

    Returns:
        Dictionary with statistics and list of observation dictionaries.
    """
    def _query(conn: sqlite3.Connection) -> dict[str, Any]:
        stats = fetch_speed_observation_stats(conn, run_id)
        rows = fetch_speed_observations_for_run(conn, run_id, track_id=track_id)
        if limit is not None and limit > 0:
            rows = rows[:limit]

        obs_list = [dict(r) for r in rows]
        return {
            "run_id": run_id,
            "track_id": track_id,
            "stats": stats,
            "count": len(obs_list),
            "observations": obs_list,
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
