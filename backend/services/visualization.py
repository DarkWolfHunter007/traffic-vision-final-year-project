"""Phase 04 visualization service.

Orchestrates trajectory extraction from tracks, frame annotation,
and preview/video rendering with provenance and failure recovery.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import cv2

from backend.config import canonical_json, config_hash
from backend.database.connection import database_connection, schema_version
from backend.database.repository import (
    fetch_run_by_id,
    fetch_tracks_for_run,
    insert_run,
    update_run_status,
)
from backend.media import iter_decoded_images, preview_frame
from backend.services.ingestion import _utc_now, current_code_version
from backend.trajectories import Trajectory, build_trajectories
from backend.visualization import VisualizationConfig, render_frame_annotations


def build_run_trajectories(
    connection: Any,
    run_id: str,
    config: dict[str, Any] | None = None,
) -> dict[int, Trajectory]:
    """Fetch stored tracks for run_id and assemble ordered Trajectory instances."""
    run = fetch_run_by_id(connection, run_id)
    if run is None:
        raise ValueError(f"Processing run does not exist: {run_id}")

    video = connection.execute(
        "SELECT video_id, width, height, frame_count FROM videos WHERE video_id = ?",
        (run["video_id"],),
    ).fetchone()

    rows = fetch_tracks_for_run(connection, run_id)
    video_width = video["width"] if video else None
    video_height = video["height"] if video else None
    last_frame = (video["frame_count"] - 1) if video and video["frame_count"] else None

    return build_trajectories(
        observations=rows,
        video_width=video_width,
        video_height=video_height,
        last_video_frame=last_frame,
        config=config,
    )


def render_preview_visualization(
    parent_run_id: str,
    frame_number: int,
    config: dict[str, Any],
    repository_root: Path,
    output_path: Path | None = None,
) -> Path:
    """Render a single annotated preview frame from a completed tracking run."""
    database_path = Path(config["paths"]["database_path"])
    if not database_path.is_absolute():
        database_path = repository_root / database_path

    with database_connection(database_path) as connection:
        parent = fetch_run_by_id(connection, parent_run_id)
        if parent is None:
            raise ValueError(f"Parent processing run does not exist: {parent_run_id}")
        if parent["status"] != "completed":
            raise ValueError(f"Parent tracking run is not completed (status={parent['status']})")

        video = connection.execute(
            "SELECT path FROM videos WHERE video_id = ?",
            (parent["video_id"],),
        ).fetchone()
        if video is None:
            raise ValueError(f"Associated video not found: {parent['video_id']}")

        video_path = Path(video["path"])
        if not video_path.is_absolute():
            video_path = repository_root / video_path

        trajectories = build_run_trajectories(connection, parent_run_id, config)

    preview = preview_frame(video_path, frame_number)
    rgb_image = preview.frame.to_ndarray(format="rgb24")

    # Find active tracks for this frame
    active_tracks: list[tuple[Trajectory, Any]] = []
    for traj in trajectories.values():
        pt = traj.point_at_frame(frame_number)
        if pt is not None:
            active_tracks.append((traj, pt))

    vis_cfg = VisualizationConfig.from_dict(config.get("visualization"))
    annotated_rgb = render_frame_annotations(rgb_image, frame_number, active_tracks, vis_cfg)
    annotated_bgr = cv2.cvtColor(annotated_rgb, cv2.COLOR_RGB2BGR)

    if output_path is None:
        vis_dir = Path(config.get("paths", {}).get("processed_root", "data/processed")) / "visualizations"
        if not vis_dir.is_absolute():
            vis_dir = repository_root / vis_dir
        vis_dir.mkdir(parents=True, exist_ok=True)
        output_path = vis_dir / f"{parent_run_id}_frame_{frame_number}.jpg"
    else:
        if not output_path.is_absolute():
            output_path = repository_root / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)

    success = cv2.imwrite(str(output_path), annotated_bgr)
    if not success:
        raise RuntimeError(f"Failed to write preview image to {output_path}")

    return output_path


def render_video_visualization(
    parent_run_id: str,
    config: dict[str, Any],
    repository_root: Path,
    output_path: Path | None = None,
    start_frame: int | None = None,
    end_frame: int | None = None,
) -> str:
    """Render a full or segment video with trajectory overlays, recording lineage in processing_runs."""
    database_path = Path(config["paths"]["database_path"])
    if not database_path.is_absolute():
        database_path = repository_root / database_path

    with database_connection(database_path) as connection:
        parent = fetch_run_by_id(connection, parent_run_id)
        if parent is None:
            raise ValueError(f"Parent processing run does not exist: {parent_run_id}")
        if parent["status"] != "completed":
            raise ValueError(f"Parent tracking run is not completed (status={parent['status']})")

        video = connection.execute(
            "SELECT path, fps_nominal, width, height FROM videos WHERE video_id = ?",
            (parent["video_id"],),
        ).fetchone()
        if video is None:
            raise ValueError(f"Associated video not found: {parent['video_id']}")

        video_path = Path(video["path"])
        if not video_path.is_absolute():
            video_path = repository_root / video_path

        trajectories = build_run_trajectories(connection, parent_run_id, config)

        run_id = str(uuid4())
        started_at = _utc_now()
        run_record = {
            "run_id": run_id,
            "parent_run_id": parent_run_id,
            "video_id": parent["video_id"],
            "model_version": parent["model_version"],
            "config_hash": config_hash(config),
            "config_json": canonical_json(config),
            "schema_version": schema_version(),
            "code_version": current_code_version(repository_root),
            "source_video_sha256": parent["source_video_sha256"],
            "started_at": started_at,
            "completed_at": None,
            "status": "running",
            "notes": None,
        }
        insert_run(connection, run_record)

    if output_path is None:
        vis_dir = Path(config.get("paths", {}).get("processed_root", "data/processed")) / "visualizations"
        if not vis_dir.is_absolute():
            vis_dir = repository_root / vis_dir
        vis_dir.mkdir(parents=True, exist_ok=True)
        output_path = vis_dir / f"{run_id}_visualized.mp4"
    else:
        if not output_path.is_absolute():
            output_path = repository_root / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)

    temp_output_path = output_path.with_name(f"{output_path.stem}.tmp{output_path.suffix}")

    fps = float(video["fps_nominal"]) if video["fps_nominal"] else 30.0
    width = int(video["width"]) if video["width"] else 1280
    height = int(video["height"]) if video["height"] else 720

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(temp_output_path), fourcc, fps, (width, height))
    vis_cfg = VisualizationConfig.from_dict(config.get("visualization"))

    rendered_count = 0
    try:
        if not writer.isOpened():
            raise RuntimeError(f"Unable to open VideoWriter for {temp_output_path}")

        for frame_number, pts_s, rgb_frame in iter_decoded_images(video_path):
            if start_frame is not None and frame_number < start_frame:
                continue
            if end_frame is not None and frame_number > end_frame:
                break

            active_tracks = []
            for traj in trajectories.values():
                pt = traj.point_at_frame(frame_number)
                if pt is not None:
                    active_tracks.append((traj, pt))

            annotated_rgb = render_frame_annotations(
                rgb_frame,
                frame_number,
                active_tracks,
                vis_cfg,
            )
            annotated_bgr = cv2.cvtColor(annotated_rgb, cv2.COLOR_RGB2BGR)
            writer.write(annotated_bgr)
            rendered_count += 1

        writer.release()

        # Atomic replacement to guarantee partial outputs are never observed as finished
        if temp_output_path.is_file():
            temp_output_path.replace(output_path)
        else:
            raise RuntimeError("Temporary output file was not created by VideoWriter")

        notes = {
            "output_path": str(output_path),
            "rendered_frames": rendered_count,
            "start_frame": start_frame,
            "end_frame": end_frame,
            "trajectories_count": len(trajectories),
        }
        with database_connection(database_path) as connection:
            update_run_status(
                connection,
                run_id,
                "completed",
                completed_at=_utc_now(),
                notes=json.dumps(notes, sort_keys=True),
            )

        return run_id

    except Exception as exc:
        writer.release()
        if temp_output_path.is_file():
            temp_output_path.unlink(missing_ok=True)

        with database_connection(database_path) as connection:
            update_run_status(
                connection,
                run_id,
                "failed",
                completed_at=_utc_now(),
                notes=json.dumps({"error": str(exc)}, sort_keys=True),
            )
        raise
