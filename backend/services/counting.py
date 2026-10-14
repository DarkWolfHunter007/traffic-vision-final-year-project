"""Phase 06 vehicle counting and ground-truth comparison service.

Orchestrates counting runs derived from tracking runs, loads ground-truth datasets,
and computes counting comparison reports.
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

from backend.config import canonical_json, config_hash
from backend.counting import (
    aggregate_volume_bins,
    calculate_counting_comparison,
    derive_movement,
    detect_crossings_for_trajectory,
)
from backend.database.connection import database_connection, schema_version
from backend.database.repository import (
    fetch_lineage_run_ids,
    fetch_counting_lines_for_video,
    fetch_crossing_events_for_run,
    fetch_ground_truth_counts_for_set,
    fetch_ground_truth_set_by_id,
    fetch_run_by_id,
    fetch_tracks_for_run,
    fetch_video_segments_for_video,
    fetch_zones_for_video,
    insert_crossing_events,
    insert_ground_truth_counts,
    insert_ground_truth_set,
    insert_run,
    insert_traffic_volume_bins,
    insert_video_segments,
    update_run_status,
)
from backend.services.ingestion import _utc_now, current_code_version
from backend.trajectories import build_trajectories

logger = logging.getLogger(__name__)


def run_counting(
    parent_run_id: str,
    config: dict[str, Any],
    repository_root: Path,
    connection: sqlite3.Connection | None = None,
) -> str:
    """Execute vehicle counting for a tracking parent run.

    Creates an immutable processing run with parent_run_id referencing the tracking run.
    """
    database_path = Path(config["paths"]["database_path"])
    if not database_path.is_absolute():
        database_path = repository_root / database_path

    counting_cfg = config.get("counting", {})
    min_reentry_gap_s = float(counting_cfg.get("min_reentry_gap_s", 2.0))
    bin_duration_s = float(counting_cfg.get("bin_duration_s", 900.0))
    movement_mapping = counting_cfg.get("movement_mapping", {})
    max_gap_seconds = float(config.get("trajectories", {}).get("max_gap_seconds", 1.0))

    run_id = str(uuid4())

    def _execute(conn: sqlite3.Connection) -> str:
        parent = fetch_run_by_id(conn, parent_run_id)
        if parent is None:
            raise ValueError(f"Parent processing run does not exist: {parent_run_id}")
        if parent["status"] != "completed":
            raise ValueError(f"Parent tracking run is not completed (status={parent['status']})")

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

        counting_lines = [dict(r) for r in fetch_counting_lines_for_video(conn, video_id)]
        zones = [dict(r) for r in fetch_zones_for_video(conn, video_id)]

        # Record new processing run
        insert_run(
            conn,
            {
                "run_id": run_id,
                "parent_run_id": parent_run_id,
                "video_id": video_id,
                "model_version": parent["model_version"],
                "config_hash": config_hash(config),
                "config_json": canonical_json({**config, RUN_STAGE_KEY: COUNTING_STAGE}),
                "schema_version": schema_version(),
                "code_version": current_code_version(repository_root),
                "source_video_sha256": parent["source_video_sha256"],
                "started_at": _utc_now(),
                "status": "running",
                "notes": COUNTING_NOTES_PREFIX,
            },
        )
        conn.commit()

        try:
            # Fetch tracks from tracking parent run
            tracks_raw = fetch_tracks_for_run(conn, parent_run_id)
            trajectories = build_trajectories(
                observations=tracks_raw,
                video_width=v_width,
                video_height=v_height,
                last_video_frame=last_frame,
                config=config,
            )

            all_crossings: list[dict[str, Any]] = []

            for track_id, traj in sorted(trajectories.items()):
                # Associate run_id for new counting output
                traj_counting = traj
                traj_counting.run_id = run_id

                # Derive turning movement from entry/exit zones
                mov, entry_app, _ = derive_movement(
                    trajectory=traj_counting,
                    zones=zones,
                    movement_mapping=movement_mapping,
                )

                # Detect line crossings
                crossings = detect_crossings_for_trajectory(
                    trajectory=traj_counting,
                    counting_lines=counting_lines,
                    min_reentry_gap_s=min_reentry_gap_s,
                    max_gap_seconds=max_gap_seconds,
                    movement=mov,
                    entry_approach=entry_app,
                )
                all_crossings.extend(crossings)

            # Insert raw crossing events
            if all_crossings:
                insert_crossing_events(conn, all_crossings)

            # Aggregate into volume bins
            bins = aggregate_volume_bins(
                crossings=all_crossings,
                run_id=run_id,
                video_id=video_id,
                bin_duration_s=bin_duration_s,
                video_duration_s=v_duration,
            )
            if bins:
                insert_traffic_volume_bins(conn, bins)

            update_run_status(conn, run_id, status="completed", completed_at=_utc_now())
            conn.commit()
            return run_id
        except Exception as err:
            update_run_status(conn, run_id, status="failed", notes=f"Failed: {err}")
            conn.commit()
            raise

    if connection is not None:
        return _execute(connection)

    with database_connection(database_path) as conn:
        return _execute(conn)


def load_ground_truth(
    file_path: Path | str,
    config: dict[str, Any] | None = None,
    repository_root: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Load a ground-truth counting dataset from YAML or JSON into canonical database tables."""
    path = Path(file_path)
    if not path.is_absolute() and repository_root:
        path = repository_root / path

    if not path.exists():
        raise FileNotFoundError(f"Ground-truth file does not exist: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    set_raw = data.get("set")
    if not isinstance(set_raw, Mapping):
        raise ValueError("Ground-truth file must contain a 'set' dictionary")

    set_id = str(set_raw.get("ground_truth_set_id") or f"gt_{uuid4().hex[:8]}")
    name = str(set_raw.get("name") or "Unnamed Ground Truth Set")
    desc = str(set_raw.get("source_description") or "Software test fixture")
    split_group = str(set_raw.get("split_group") or "test")
    created_at = str(set_raw.get("created_at") or _utc_now())

    gt_set_record = {
        "ground_truth_set_id": set_id,
        "name": name,
        "source_description": desc,
        "split_group": split_group,
        "created_at": created_at,
    }

    segments_raw = data.get("segments", [])
    if not isinstance(segments_raw, list):
        raise ValueError("segments must be a list")

    validated_segments: list[dict[str, Any]] = []
    for s_idx, s in enumerate(segments_raw):
        if not isinstance(s, Mapping):
            raise ValueError(f"Segment at index {s_idx} must be a dictionary")
        seg_id = str(s.get("segment_id") or f"seg_{uuid4().hex[:8]}")
        vid_id = str(s.get("video_id", ""))
        if not vid_id:
            raise ValueError(f"Segment at index {s_idx} missing required 'video_id'")
        start_s = float(s.get("start_s", 0.0))
        end_s = float(s.get("end_s", 0.0))
        if start_s > end_s:
            raise ValueError(f"Segment {seg_id} start_s ({start_s}) > end_s ({end_s})")
        start_fn = int(s.get("start_frame", 0))
        end_fn = int(s.get("end_frame", 0))

        validated_segments.append(
            {
                "segment_id": seg_id,
                "video_id": vid_id,
                "start_s": start_s,
                "end_s": end_s,
                "start_frame": start_fn,
                "end_frame": end_fn,
                "label": s.get("label"),
                "condition_notes": s.get("condition_notes"),
            }
        )

    counts_raw = data.get("counts", [])
    if not isinstance(counts_raw, list):
        raise ValueError("counts must be a list")

    validated_counts: list[dict[str, Any]] = []
    for c_idx, c in enumerate(counts_raw):
        if not isinstance(c, Mapping):
            raise ValueError(f"Count at index {c_idx} must be a dictionary")
        count_id = str(c.get("ground_truth_count_id") or f"gtc_{uuid4().hex[:8]}")
        seg_id = str(c.get("video_segment_id", ""))
        if not seg_id:
            raise ValueError(f"Count at index {c_idx} missing 'video_segment_id'")
        app = str(c.get("approach", ""))
        mov = str(c.get("movement", ""))
        obs = int(c.get("observed_count", 0))

        validated_counts.append(
            {
                "ground_truth_count_id": count_id,
                "ground_truth_set_id": set_id,
                "video_segment_id": seg_id,
                "approach": app,
                "movement": mov,
                "vehicle_class": c.get("vehicle_class"),
                "observed_count": obs,
            }
        )

    def _execute(conn: sqlite3.Connection) -> dict[str, Any]:
        # Validate foreign keys
        for seg in validated_segments:
            v_exists = conn.execute(
                "SELECT 1 FROM videos WHERE video_id = ?",
                (seg["video_id"],),
            ).fetchone()
            if not v_exists:
                raise ValueError(f"Segment references non-existent video: {seg['video_id']}")

        # Persist ground truth set, segments, counts
        insert_ground_truth_set(conn, gt_set_record)
        if validated_segments:
            insert_video_segments(conn, validated_segments)
        if validated_counts:
            insert_ground_truth_counts(conn, validated_counts)
        conn.commit()

        return {
            "status": "loaded",
            "ground_truth_set_id": set_id,
            "segments_count": len(validated_segments),
            "counts_count": len(validated_counts),
        }

    if connection is not None:
        return _execute(connection)

    database_path = (
        Path(config["paths"]["database_path"])
        if config
        else Path("data/processed/traffic_vision.sqlite3")
    )
    if not database_path.is_absolute() and repository_root:
        database_path = repository_root / database_path

    with database_connection(database_path) as conn:
        return _execute(conn)


RUN_STAGE_KEY = "_run_stage"
COUNTING_STAGE = "counting"
COUNTING_NOTES_PREFIX = "Phase 06 vehicle counting run"


def _is_counting_run(conn: sqlite3.Connection, run: Any) -> bool:
    """True if the run is a counting-stage run (structured marker, volume bins, or crossings)."""
    try:
        cfg = json.loads(run["config_json"] or "{}")
        if isinstance(cfg, dict) and cfg.get(RUN_STAGE_KEY) == COUNTING_STAGE:
            return True
    except (TypeError, ValueError):
        pass
    if str(run["notes"] or "").startswith(COUNTING_NOTES_PREFIX):
        return True
    rid = run["run_id"]
    if conn.execute("SELECT 1 FROM traffic_volume_bins WHERE run_id = ? LIMIT 1", (rid,)).fetchone():
        return True
    return bool(fetch_crossing_events_for_run(conn, rid))


def compare_counts(
    run_id: str,
    ground_truth_set_id: str | None = None,
    config: dict[str, Any] | None = None,
    repository_root: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Compare counted vehicles from a counting run against a ground-truth dataset.

    Invariant: Records error_tolerance_pct but MUST NOT state that the counter passed or was accepted.
    """
    def _execute(conn: sqlite3.Connection) -> dict[str, Any]:
        run = fetch_run_by_id(conn, run_id)
        if run is None:
            raise ValueError(f"Counting processing run not found: {run_id}")

        video_id = str(run["video_id"])

        # Determine ground_truth_set_id if omitted
        target_set_id = ground_truth_set_id
        if not target_set_id:
            row = conn.execute(
                """
                SELECT DISTINCT c.ground_truth_set_id
                FROM ground_truth_counts c
                JOIN video_segments v ON c.video_segment_id = v.segment_id
                WHERE v.video_id = ?
                ORDER BY c.ground_truth_set_id ASC
                LIMIT 1
                """,
                (video_id,),
            ).fetchone()
            if not row:
                raise ValueError(f"No ground-truth dataset found for video '{video_id}'")
            target_set_id = row[0]

        gt_set = fetch_ground_truth_set_by_id(conn, target_set_id)
        if gt_set is None:
            raise ValueError(f"Ground-truth set '{target_set_id}' not found")

        # Fetch video segments associated with this ground truth set
        segments = conn.execute(
            """
            SELECT DISTINCT v.segment_id, v.video_id, v.start_s, v.end_s, v.start_frame, v.end_frame,
                            v.label, v.condition_notes
            FROM video_segments v
            JOIN ground_truth_counts c ON v.segment_id = c.video_segment_id
            WHERE c.ground_truth_set_id = ?
            ORDER BY v.start_s ASC
            """,
            (target_set_id,),
        ).fetchall()

        gt_counts = fetch_ground_truth_counts_for_set(conn, target_set_id)
        if str(run["status"]) != "completed":
            raise ValueError(
                f"Run '{run_id}' has status '{run['status']}', not 'completed'; "
                "ground-truth comparison unavailable"
            )
        if _is_counting_run(conn, run):
            # A counting run is authoritative for its own results, even when it has zero crossings.
            crossings = fetch_crossing_events_for_run(conn, run_id)
        else:
            # Non-counting run (e.g. review): borrow from the single completed counting run in lineage.
            candidates = []
            for rid in fetch_lineage_run_ids(conn, run_id):
                if rid == run_id:
                    continue
                cand = fetch_run_by_id(conn, rid)
                if (
                    cand is not None
                    and str(cand["status"]) == "completed"
                    and str(cand["video_id"]) == video_id
                    and _is_counting_run(conn, cand)
                ):
                    candidates.append(rid)
            if len(candidates) > 1:
                raise ValueError(
                    f"Run '{run_id}' is not a counting run and multiple related counting runs exist "
                    f"({', '.join(candidates)}); ground-truth comparison unavailable"
                )
            if not candidates:
                raise ValueError(
                    f"Run '{run_id}' has no completed counting run in its lineage; "
                    "ground-truth comparison unavailable"
                )
            crossings = fetch_crossing_events_for_run(conn, candidates[0])

        error_tol = float((config or {}).get("counting", {}).get("error_tolerance_pct", 10.0))

        report = calculate_counting_comparison(
            counted_events=[dict(r) for r in crossings],
            ground_truth_counts=[dict(r) for r in gt_counts],
            video_segments=[dict(s) for s in segments],
            error_tolerance_pct=error_tol,
        )

        report["run_id"] = run_id
        report["video_id"] = video_id
        report["ground_truth_set_id"] = target_set_id
        report["ground_truth_set_name"] = gt_set["name"]
        return report

    if connection is not None:
        return _execute(connection)

    database_path = (
        Path(config["paths"]["database_path"])
        if config
        else Path("data/processed/traffic_vision.sqlite3")
    )
    if not database_path.is_absolute() and repository_root:
        database_path = repository_root / database_path

    with database_connection(database_path) as conn:
        return _execute(conn)
