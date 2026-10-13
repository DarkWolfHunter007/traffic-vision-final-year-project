"""Phase 07 camera calibration service orchestration.

Coordinates planar homography calibration runs, persists results into
canonical calibration_runs and calibration_points tables, and provides
calibration inspection and retrieval.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

import yaml

from backend.calibration import CalibrationResult, calibrate_camera
from backend.config import canonical_json, config_hash
from backend.database.connection import database_connection, schema_version
from backend.database.repository import (
    fetch_calibration_points_for_run,
    fetch_calibration_run_by_id,
    fetch_run_by_id,
    insert_calibration_points,
    insert_calibration_run,
    insert_run,
)
from backend.services.ingestion import _utc_now, current_code_version

logger = logging.getLogger(__name__)


def load_calibration_points(file_path: Path | str) -> list[dict[str, Any]]:
    """Load reference point correspondences from a YAML or JSON file.

    Supported formats:
    1. A mapping containing a 'points' list: {"points": [{"image_x": ..., ...}, ...]}
    2. A top-level list of point mappings: [{"image_x": ..., ...}, ...]

    Parameters:
        file_path: Path to the YAML or JSON file.

    Returns:
        List of point correspondence dictionaries.

    Raises:
        FileNotFoundError: If file does not exist.
        ValueError: If file content is malformed or empty.
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Calibration points file does not exist: {path}")

    try:
        content = path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
    except Exception as error:
        raise ValueError(f"Failed to parse calibration points file {path}: {error}") from error

    if isinstance(data, Mapping) and "points" in data:
        points = data["points"]
    elif isinstance(data, list):
        points = data
    else:
        raise ValueError(
            f"Invalid calibration points format in {path}: expected a list of points "
            "or a mapping with a 'points' key."
        )

    if not isinstance(points, list) or len(points) == 0:
        raise ValueError(f"No reference points found in {path}")

    for idx, pt in enumerate(points):
        if not isinstance(pt, Mapping):
            raise ValueError(f"Point at index {idx} in {path} must be a dictionary/mapping")

    return [dict(p) for p in points]


def run_calibration(
    parent_run_or_video_id: str,
    points_file_or_data: Path | str | list[dict[str, Any]],
    config: dict[str, Any],
    repository_root: Path,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Execute camera calibration and record results with full provenance.

    Parameters:
        parent_run_or_video_id: An existing processing_runs(run_id) or videos(video_id).
        points_file_or_data: Path to points file or in-memory list of point dicts.
        config: Loaded project configuration.
        repository_root: Path to repository root.
        connection: Optional existing SQLite database connection.

    Returns:
        Summary dict containing calibration_id, run_id, acceptance status,
        and reprojection error diagnostics.

    Raises:
        ValueError: If target does not exist, points are invalid/collinear, or calibration fails.
    """
    database_path = Path(config["paths"]["database_path"])
    if not database_path.is_absolute():
        database_path = repository_root / database_path

    # Load points if given as path
    if isinstance(points_file_or_data, (str, Path)):
        p_path = Path(points_file_or_data)
        if not p_path.is_absolute():
            p_path = repository_root / p_path
        points = load_calibration_points(p_path)
    elif isinstance(points_file_or_data, list):
        points = points_file_or_data
    else:
        raise ValueError(f"Unsupported points_file_or_data type: {type(points_file_or_data)}")

    def _execute(conn: sqlite3.Connection) -> dict[str, Any]:
        # Resolve target video_id and parent_run_id
        parent = fetch_run_by_id(conn, parent_run_or_video_id)
        if parent is not None:
            video_id = str(parent["video_id"])
            parent_run_id: str | None = str(parent["run_id"])
            source_video_sha256 = str(parent["source_video_sha256"])
        else:
            # Check if target is a video_id
            v_row = conn.execute(
                "SELECT video_id, sha256 FROM videos WHERE video_id = ?",
                (parent_run_or_video_id,),
            ).fetchone()
            if v_row is None:
                raise ValueError(
                    f"Target '{parent_run_or_video_id}' is neither a known run_id nor video_id"
                )
            video_id = str(v_row["video_id"])
            source_video_sha256 = str(v_row["sha256"])
            # Lookup latest run for this video if available
            latest_run = conn.execute(
                "SELECT run_id FROM processing_runs WHERE video_id = ? ORDER BY started_at DESC LIMIT 1",
                (video_id,),
            ).fetchone()
            parent_run_id = str(latest_run["run_id"]) if latest_run else None

        # Execute pure calibration
        calib_result: CalibrationResult = calibrate_camera(points, config=config)

        # Generate IDs
        run_id = str(uuid4())
        calibration_id = calib_result.calibration_id

        # Insert child processing_run record
        now_ts = _utc_now()
        insert_run(
            conn,
            {
                "run_id": run_id,
                "parent_run_id": parent_run_id,
                "video_id": video_id,
                "model_version": None,
                "config_hash": config_hash(config),
                "config_json": canonical_json(config),
                "schema_version": schema_version(),
                "code_version": current_code_version(repository_root),
                "source_video_sha256": source_video_sha256,
                "started_at": now_ts,
                "status": "completed",
                "notes": f"Phase 07 camera calibration run (accepted={int(calib_result.accepted)})",
            },
        )
        # Update completed_at
        conn.execute(
            "UPDATE processing_runs SET completed_at = ? WHERE run_id = ?",
            (now_ts, run_id),
        )

        # Insert calibration_runs record
        insert_calibration_run(
            conn,
            {
                "calibration_id": calibration_id,
                "run_id": run_id,
                "video_id": video_id,
                "method": calib_result.method,
                "point_count": calib_result.point_count,
                "held_out_point_count": calib_result.held_out_point_count,
                "reprojection_error_m_mean": calib_result.reprojection_error_m_mean,
                "reprojection_error_m_max": calib_result.reprojection_error_m_max,
                "distortion_checked": int(calib_result.distortion_checked),
                "flat_road_assumption": int(calib_result.flat_road_assumption),
                "accepted": int(calib_result.accepted),
                "parameters_json": calib_result.parameters_json,
            },
        )

        # Insert calibration_points records
        points_to_insert = [
            {
                "calibration_point_id": pt["calibration_point_id"],
                "calibration_id": calibration_id,
                "role": pt["role"],
                "image_x": pt["image_x"],
                "image_y": pt["image_y"],
                "world_x": pt["world_x"],
                "world_y": pt["world_y"],
            }
            for pt in calib_result.points
        ]
        insert_calibration_points(conn, points_to_insert)

        return {
            "calibration_id": calibration_id,
            "run_id": run_id,
            "parent_run_id": parent_run_id,
            "video_id": video_id,
            "method": calib_result.method,
            "point_count": calib_result.point_count,
            "held_out_point_count": calib_result.held_out_point_count,
            "reprojection_error_m_mean": calib_result.reprojection_error_m_mean,
            "reprojection_error_m_max": calib_result.reprojection_error_m_max,
            "fit_reprojection_error_m_mean": calib_result.fit_reprojection_error_m_mean,
            "fit_reprojection_error_m_max": calib_result.fit_reprojection_error_m_max,
            "accepted": calib_result.accepted,
            "distortion_checked": calib_result.distortion_checked,
            "flat_road_assumption": calib_result.flat_road_assumption,
        }

    if connection is not None:
        return _execute(connection)

    with database_connection(database_path) as conn:
        return _execute(conn)


def get_calibration(
    calibration_id: str,
    config: dict[str, Any] | None = None,
    repository_root: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any] | None:
    """Retrieve full calibration details, matrix parameters, and point correspondences.

    Parameters:
        calibration_id: Primary key of calibration_runs.
        config: Optional project configuration.
        repository_root: Optional repository root path.
        connection: Optional database connection.

    Returns:
        Dictionary of calibration details, or None if not found.
    """
    def _query(conn: sqlite3.Connection) -> dict[str, Any] | None:
        run_row = fetch_calibration_run_by_id(conn, calibration_id)
        if run_row is None:
            return None

        points_rows = fetch_calibration_points_for_run(conn, calibration_id)
        try:
            params = json.loads(run_row["parameters_json"])
        except Exception:
            params = {}

        return {
            "calibration_id": run_row["calibration_id"],
            "run_id": run_row["run_id"],
            "video_id": run_row["video_id"],
            "method": run_row["method"],
            "point_count": run_row["point_count"],
            "held_out_point_count": run_row["held_out_point_count"],
            "reprojection_error_m_mean": run_row["reprojection_error_m_mean"],
            "reprojection_error_m_max": run_row["reprojection_error_m_max"],
            "distortion_checked": bool(run_row["distortion_checked"]),
            "flat_road_assumption": bool(run_row["flat_road_assumption"]),
            "accepted": bool(run_row["accepted"]),
            "parameters": params,
            "points": [
                {
                    "calibration_point_id": p["calibration_point_id"],
                    "role": p["role"],
                    "image_x": p["image_x"],
                    "image_y": p["image_y"],
                    "world_x": p["world_x"],
                    "world_y": p["world_y"],
                }
                for p in points_rows
            ],
        }

    if connection is not None:
        return _query(connection)

    if config is not None:
        db_path = Path(config["paths"]["database_path"])
        if repository_root and not db_path.is_absolute():
            db_path = repository_root / db_path
        with database_connection(db_path) as conn:
            return _query(conn)

    raise ValueError("Either an open database connection or config must be provided")
