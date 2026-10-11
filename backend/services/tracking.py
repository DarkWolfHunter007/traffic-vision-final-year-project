"""Phase 03 ByteTrack run orchestration; downstream analytics remain excluded."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.config import canonical_json, config_hash
from backend.database.connection import database_connection, schema_version
from backend.database.repository import (
    fetch_detections_for_tracking,
    insert_run,
    insert_tracks,
    update_run_status,
)
from backend.detection import Detection
from backend.services.ingestion import _utc_now, current_code_version
from backend.tracking import (
    ByteTrackerAdapter,
    TrackObservation,
    Tracker,
    cadence_to_frames,
)


def run_tracking(
    parent_run_id: str,
    config: dict[str, Any],
    repository_root: Path,
    tracker: Tracker | None = None,
) -> str:
    """Create one immutable tracking run derived from a completed detection parent run."""
    database_path = Path(config["paths"]["database_path"])
    if not database_path.is_absolute():
        database_path = repository_root / database_path

    tracking_cfg = config.get("tracking", {})
    batch_size = max(1, int(tracking_cfg.get("batch_size") or config.get("streaming", {}).get("frame_batch_size", 500)))
    run_id = str(uuid4())

    with database_connection(database_path) as connection:
        parent = connection.execute(
            """
            SELECT run_id, video_id, model_version, config_json, source_video_sha256, status
            FROM processing_runs
            WHERE run_id = ?
            """,
            (parent_run_id,),
        ).fetchone()
        if parent is None:
            raise ValueError(f"Parent processing run does not exist: {parent_run_id}")
        if parent["status"] != "completed":
            raise ValueError(f"Parent detection run is not completed (status={parent['status']})")

        video = connection.execute(
            "SELECT video_id, fps_nominal FROM videos WHERE video_id = ?",
            (parent["video_id"],),
        ).fetchone()
        if video is None:
            raise ValueError("Parent run references a missing video")

        parent_config = json.loads(parent["config_json"])
        frame_stride = parent_config.get("detection", {}).get("frame_stride", 1)
        nominal_fps = float(video["fps_nominal"]) if video["fps_nominal"] else 30.0

        track_buffer_frames = cadence_to_frames(
            tracking_cfg.get("track_buffer_seconds", 1.0),
            nominal_fps,
            frame_stride,
        )

        if tracker is None:
            tracker = ByteTrackerAdapter(
                track_high_thresh=tracking_cfg.get("track_high_thresh", 0.5),
                track_low_thresh=tracking_cfg.get("track_low_thresh", 0.1),
                new_track_thresh=tracking_cfg.get("new_track_thresh", 0.6),
                match_thresh=tracking_cfg.get("match_thresh", 0.8),
                track_buffer_frames=track_buffer_frames,
                fuse_score=tracking_cfg.get("fuse_score", True),
            )

        insert_run(
            connection,
            {
                "run_id": run_id,
                "parent_run_id": parent_run_id,
                "video_id": parent["video_id"],
                "model_version": parent["model_version"],
                "config_hash": config_hash(config),
                "config_json": canonical_json(config),
                "schema_version": schema_version(),
                "code_version": current_code_version(repository_root),
                "source_video_sha256": parent["source_video_sha256"],
                "started_at": _utc_now(),
                "status": "running",
                "notes": "Phase 03 ByteTrack tracking run",
            },
        )

    try:
        with database_connection(database_path) as connection:
            bounds = connection.execute(
                """
                SELECT MIN(frame_number) AS min_fn, MAX(frame_number) AS max_fn, COUNT(*) AS frame_cnt
                FROM video_frames
                WHERE video_id = ?
                """,
                (parent["video_id"],),
            ).fetchone()

            min_fn = bounds["min_fn"] if bounds and bounds["min_fn"] is not None else 0
            max_fn = bounds["max_fn"] if bounds and bounds["max_fn"] is not None else -1
            frame_cnt = bounds["frame_cnt"] if bounds and bounds["frame_cnt"] is not None else 0

            pending_rows: list[dict[str, Any]] = []
            chunk_size = max(batch_size, 500)

            if frame_cnt > 0:
                for chunk_start in range(min_fn, max_fn + 1, chunk_size):
                    chunk_end = min(chunk_start + chunk_size - 1, max_fn)
                    raw_detections = fetch_detections_for_tracking(
                        connection, parent_run_id, start_frame=chunk_start, end_frame=chunk_end
                    )
                    detections_by_frame: dict[int, list[Detection]] = {}
                    for row in raw_detections:
                        fn = row["frame_number"]
                        detections_by_frame.setdefault(fn, []).append(
                            Detection(
                                class_id=row["class_id"],
                                class_name=row["class_name"],
                                confidence=row["confidence"],
                                x1=row["x1"],
                                y1=row["y1"],
                                x2=row["x2"],
                                y2=row["y2"],
                            )
                        )

                    frame_rows = connection.execute(
                        """
                        SELECT frame_number, pts_s
                        FROM video_frames
                        WHERE video_id = ? AND frame_number BETWEEN ? AND ?
                        ORDER BY frame_number ASC
                        """,
                        (parent["video_id"], chunk_start, chunk_end),
                    ).fetchall()

                    for frame_row in frame_rows:
                        fn = frame_row["frame_number"]
                        if fn % frame_stride:
                            continue
                        pts_s = frame_row["pts_s"]
                        frame_dets = detections_by_frame.get(fn, [])
                        obs_list = tracker.update(fn, pts_s, frame_dets)

                        for obs in obs_list:
                            pending_rows.append(
                                {
                                    "track_observation_id": str(uuid4()),
                                    "run_id": run_id,
                                    "video_id": parent["video_id"],
                                    "track_id": obs.track_id,
                                    "frame_number": obs.frame_number,
                                    "timestamp_s": obs.timestamp_s,
                                    "vehicle_class": obs.vehicle_class,
                                    "confidence": obs.confidence,
                                    "x1": obs.x1,
                                    "y1": obs.y1,
                                    "x2": obs.x2,
                                    "y2": obs.y2,
                                    "ground_x": obs.ground_x,
                                    "ground_y": obs.ground_y,
                                    "world_x": None,
                                    "world_y": None,
                                    "calibration_id": None,
                                    "trajectory_status": obs.trajectory_status,
                                }
                            )
                            if len(pending_rows) >= batch_size:
                                insert_tracks(connection, pending_rows)
                                pending_rows.clear()

            if pending_rows:
                insert_tracks(connection, pending_rows)
                pending_rows.clear()

            metrics = tracker.metrics
            id_switches_display = (
                str(metrics.id_switches) if metrics.id_switches is not None else "unmeasured"
            )
            notes = (
                f"Phase 03 ByteTrack run completed. "
                f"total_tracks={metrics.total_tracks}, "
                f"active_tracks={metrics.active_tracks}, "
                f"observations={metrics.total_observations}, "
                f"id_switches={id_switches_display}"
            )
            update_run_status(connection, run_id, "completed", completed_at=_utc_now(), notes=notes)

    except Exception as error:
        with database_connection(database_path) as connection:
            update_run_status(connection, run_id, "failed", completed_at=_utc_now(), notes=str(error))
        raise

    return run_id
