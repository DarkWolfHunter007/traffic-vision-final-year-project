"""Phase 10 manual review and human-in-the-loop correction service orchestration.

Coordinates uncertainty candidate filtering, validation of human corrections,
append-only persistence into canonical manual_reviews table, and event snippet generation.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import sqlite3
from typing import Any, Mapping, Sequence
from uuid import uuid4

import cv2
import numpy as np

from backend.config import load_config
from backend.database.connection import database_connection
from backend.database.repository import (
    fetch_detection_by_id,
    fetch_detections_for_tracking,
    fetch_manual_review_by_id,
    fetch_manual_review_stats,
    fetch_manual_reviews,
    fetch_run_by_id,
    fetch_track_observation_by_id,
    fetch_tracks_for_run,
    insert_manual_review,
    update_manual_review_record,
)
from backend.media import iter_decoded_images
from backend.review import (
    ManualReview,
    ReviewBox,
    compute_snippet_window,
    identify_uncertain_detections,
    identify_uncertain_tracks,
    validate_bounding_box,
    validate_class_label,
    validate_status_transition,
)
from backend.services.ingestion import _utc_now

logger = logging.getLogger(__name__)


def _resolve_paths(
    config: dict[str, Any] | None, repository_root: Path | None
) -> tuple[dict[str, Any], Path, Path]:
    repo_root = repository_root or Path(__file__).resolve().parents[2]
    cfg = config or load_config()
    db_path = Path(cfg["paths"]["database_path"])
    if not db_path.is_absolute():
        db_path = repo_root / db_path
    return cfg, repo_root, db_path


def find_review_candidates(
    parent_run_id: str,
    confidence_threshold: float | None = None,
    limit: int | None = None,
    config: dict[str, Any] | None = None,
    repository_root: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Identify low-confidence detection and tracking candidates flagged for review."""
    cfg, repo_root, db_path = _resolve_paths(config, repository_root)
    threshold = (
        float(confidence_threshold)
        if confidence_threshold is not None
        else float(cfg.get("review", {}).get("confidence_threshold", 0.50))
    )

    def _execute(conn: sqlite3.Connection) -> dict[str, Any]:
        parent = fetch_run_by_id(conn, parent_run_id)
        if parent is None:
            raise ValueError(f"Parent processing run does not exist: {parent_run_id}")
        if parent["status"] != "completed":
            raise ValueError(f"Parent processing run is not completed (status={parent['status']})")

        # Fetch detections for run (or parent detection run if tracking run)
        detections = fetch_detections_for_tracking(conn, parent_run_id)
        if not detections and parent["parent_run_id"]:
            detections = fetch_detections_for_tracking(conn, parent["parent_run_id"])

        tracks = fetch_tracks_for_run(conn, parent_run_id)

        candidates = []
        if detections:
            candidates.extend(identify_uncertain_detections(detections, threshold))
        if tracks:
            candidates.extend(identify_uncertain_tracks(tracks, threshold))

        # Sort candidates deterministically by timestamp_s, then frame_number
        candidates.sort(key=lambda c: (c.timestamp_s, c.frame_number, c.item_id))

        if limit is not None and limit > 0:
            candidates = candidates[:limit]

        return {
            "parent_run_id": parent_run_id,
            "confidence_threshold": threshold,
            "candidate_count": len(candidates),
            "candidates": [c.to_dict() for c in candidates],
        }

    if connection is not None:
        return _execute(connection)

    with database_connection(db_path) as conn:
        return _execute(conn)


def create_manual_review(
    parent_run_id: str,
    frame_number: int,
    timestamp_s: float,
    reason: str,
    detection_id: str | None = None,
    track_id: int | None = None,
    reviewer: str = "analyst",
    original_class: str | None = None,
    corrected_class: str | None = None,
    original_bbox: ReviewBox | Mapping[str, Any] | Sequence[float] | None = None,
    corrected_bbox: ReviewBox | Mapping[str, Any] | Sequence[float] | None = None,
    status: str = "pending",
    generate_snippet: bool = False,
    config: dict[str, Any] | None = None,
    repository_root: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Create an append-only manual review record, validating geometry and allowed classes."""
    cfg, repo_root, db_path = _resolve_paths(config, repository_root)
    review_cfg = cfg.get("review", {})
    allowed_classes = review_cfg.get("allowed_classes")
    allowed_statuses = review_cfg.get("review_statuses", ("pending", "approved", "rejected"))

    if not reason or not reason.strip():
        raise ValueError("Review reason must be a non-empty string")
    if not reviewer or not reviewer.strip():
        raise ValueError("Reviewer identifier must be a non-empty string")

    # Validate review status
    validated_status = validate_status_transition(None, status, allowed_statuses=allowed_statuses)

    # Validate corrected class if provided
    validated_corrected_class = validate_class_label(corrected_class, allowed_classes=allowed_classes)

    def _execute(conn: sqlite3.Connection) -> dict[str, Any]:
        parent = fetch_run_by_id(conn, parent_run_id)
        if parent is None:
            raise ValueError(f"Parent processing run does not exist: {parent_run_id}")

        video_id = str(parent["video_id"])
        video = conn.execute(
            "SELECT video_id, path, width, height, duration_s, fps_nominal FROM videos WHERE video_id = ?",
            (video_id,),
        ).fetchone()
        if video is None:
            raise ValueError(f"Video '{video_id}' referenced by run '{parent_run_id}' does not exist")

        v_width = int(video["width"]) if video["width"] is not None else None
        v_height = int(video["height"]) if video["height"] is not None else None
        v_duration = float(video["duration_s"]) if video["duration_s"] is not None else None

        # Resolve original prediction values if not provided directly
        resolved_orig_class = original_class
        resolved_orig_bbox_json = None
        if original_bbox is not None:
            orig_box = validate_bounding_box(original_bbox, frame_width=v_width, frame_height=v_height)
            resolved_orig_bbox_json = orig_box.to_json()

        if resolved_orig_class is None and detection_id:
            det = fetch_detection_by_id(conn, detection_id)
            if det:
                resolved_orig_class = str(det["class_name"])
                if resolved_orig_bbox_json is None:
                    resolved_orig_bbox_json = ReviewBox(
                        x1=float(det["x1"]),
                        y1=float(det["y1"]),
                        x2=float(det["x2"]),
                        y2=float(det["y2"]),
                    ).to_json()

        if resolved_orig_class is None and track_id is not None:
            track_obs = conn.execute(
                "SELECT vehicle_class, x1, y1, x2, y2 FROM tracks WHERE run_id = ? AND track_id = ? AND frame_number = ?",
                (parent_run_id, track_id, frame_number),
            ).fetchone()
            if track_obs:
                resolved_orig_class = str(track_obs["vehicle_class"]) if track_obs["vehicle_class"] else None
                if resolved_orig_bbox_json is None and track_obs["x1"] is not None:
                    resolved_orig_bbox_json = ReviewBox(
                        x1=float(track_obs["x1"]),
                        y1=float(track_obs["y1"]),
                        x2=float(track_obs["x2"]),
                        y2=float(track_obs["y2"]),
                    ).to_json()

        # Validate corrected bounding box against frame dimensions (reject out-of-frame edits)
        resolved_corr_bbox_json = None
        if corrected_bbox is not None:
            corr_box = validate_bounding_box(corrected_bbox, frame_width=v_width, frame_height=v_height)
            resolved_corr_bbox_json = corr_box.to_json()

        review_id = str(uuid4())
        reviewed_at = _utc_now()
        snippet_path_str: str | None = None

        if generate_snippet:
            video_path = Path(video["path"])
            if not video_path.is_absolute():
                video_path = repo_root / video_path
            out_dir = Path(review_cfg.get("output_dir", "data/processed/review_snippets"))
            if not out_dir.is_absolute():
                out_dir = repo_root / out_dir
            out_dir.mkdir(parents=True, exist_ok=True)
            snippet_file = out_dir / f"snippet_{review_id}.mp4"
            created_path = create_snippet_file(
                video_path=video_path,
                timestamp_s=timestamp_s,
                output_path=snippet_file,
                before_s=float(review_cfg.get("snippet_before_s", 1.0)),
                after_s=float(review_cfg.get("snippet_after_s", 1.0)),
                duration_s=v_duration,
                width=v_width,
                height=v_height,
                fps=float(video["fps_nominal"]) if video["fps_nominal"] else 30.0,
            )
            snippet_path_str = str(created_path)

        review_record = {
            "review_id": review_id,
            "run_id": parent_run_id,
            "video_id": video_id,
            "track_id": track_id,
            "detection_id": detection_id,
            "frame_number": int(frame_number),
            "timestamp_s": float(timestamp_s),
            "original_class": resolved_orig_class,
            "corrected_class": validated_corrected_class,
            "original_bbox_json": resolved_orig_bbox_json,
            "corrected_bbox_json": resolved_corr_bbox_json,
            "reason": reason.strip(),
            "review_status": validated_status,
            "reviewer": reviewer.strip(),
            "reviewed_at": reviewed_at,
            "snippet_path": snippet_path_str,
        }

        # Append-only insertion into canonical manual_reviews table
        insert_manual_review(conn, review_record)
        conn.commit()

        return review_record

    if connection is not None:
        return _execute(connection)

    with database_connection(db_path) as conn:
        return _execute(conn)


def get_manual_reviews(
    run_id: str | None = None,
    video_id: str | None = None,
    review_status: str | None = None,
    reviewer: str | None = None,
    track_id: int | None = None,
    detection_id: str | None = None,
    limit: int | None = None,
    config: dict[str, Any] | None = None,
    repository_root: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Retrieve manual review records matching search filters."""
    cfg, repo_root, db_path = _resolve_paths(config, repository_root)

    def _execute(conn: sqlite3.Connection) -> dict[str, Any]:
        rows = fetch_manual_reviews(
            conn,
            run_id=run_id,
            video_id=video_id,
            review_status=review_status,
            reviewer=reviewer,
            track_id=track_id,
            detection_id=detection_id,
            limit=limit,
        )
        return {
            "count": len(rows),
            "reviews": [dict(r) for r in rows],
        }

    if connection is not None:
        return _execute(connection)

    with database_connection(db_path) as conn:
        return _execute(conn)


def get_manual_review_by_id(
    review_id: str,
    config: dict[str, Any] | None = None,
    repository_root: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any] | None:
    """Retrieve a single manual review record by ID."""
    cfg, repo_root, db_path = _resolve_paths(config, repository_root)

    def _execute(conn: sqlite3.Connection) -> dict[str, Any] | None:
        row = fetch_manual_review_by_id(conn, review_id)
        if row is None:
            return None
        return dict(row)

    if connection is not None:
        return _execute(conn)

    with database_connection(db_path) as conn:
        return _execute(conn)


def update_manual_review(
    review_id: str,
    status: str | None = None,
    corrected_class: str | None = None,
    corrected_bbox: ReviewBox | Mapping[str, Any] | Sequence[float] | None = None,
    reviewer: str | None = None,
    reason: str | None = None,
    config: dict[str, Any] | None = None,
    repository_root: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Update a manual review record with validation and updated reviewed_at timestamp."""
    cfg, repo_root, db_path = _resolve_paths(config, repository_root)
    review_cfg = cfg.get("review", {})
    allowed_classes = review_cfg.get("allowed_classes")
    allowed_statuses = review_cfg.get("review_statuses", ("pending", "approved", "rejected"))

    def _execute(conn: sqlite3.Connection) -> dict[str, Any]:
        existing = fetch_manual_review_by_id(conn, review_id)
        if existing is None:
            raise ValueError(f"Manual review record not found: {review_id}")

        video_id = str(existing["video_id"])
        video = conn.execute(
            "SELECT width, height FROM videos WHERE video_id = ?",
            (video_id,),
        ).fetchone()
        v_width = int(video["width"]) if video and video["width"] is not None else None
        v_height = int(video["height"]) if video and video["height"] is not None else None

        updates: dict[str, object] = {}

        if status is not None:
            validated_status = validate_status_transition(
                existing["review_status"], status, allowed_statuses=allowed_statuses
            )
            updates["review_status"] = validated_status

        if corrected_class is not None:
            validated_class = validate_class_label(corrected_class, allowed_classes=allowed_classes)
            updates["corrected_class"] = validated_class

        if corrected_bbox is not None:
            validated_bbox = validate_bounding_box(
                corrected_bbox, frame_width=v_width, frame_height=v_height
            )
            updates["corrected_bbox_json"] = validated_bbox.to_json()

        if reviewer is not None:
            if not reviewer.strip():
                raise ValueError("Reviewer identifier must be a non-empty string")
            updates["reviewer"] = reviewer.strip()

        if reason is not None:
            if not reason.strip():
                raise ValueError("Review reason must be a non-empty string")
            updates["reason"] = reason.strip()

        updates["reviewed_at"] = _utc_now()

        update_manual_review_record(conn, review_id, updates)
        conn.commit()

        updated = fetch_manual_review_by_id(conn, review_id)
        return dict(updated) if updated else updates

    if connection is not None:
        return _execute(connection)

    with database_connection(db_path) as conn:
        return _execute(conn)


def generate_snippet_for_review(
    review_id: str,
    config: dict[str, Any] | None = None,
    repository_root: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> Path:
    """Generate event snippet for an existing review record and record snippet_path."""
    cfg, repo_root, db_path = _resolve_paths(config, repository_root)
    review_cfg = cfg.get("review", {})

    def _execute(conn: sqlite3.Connection) -> Path:
        existing = fetch_manual_review_by_id(conn, review_id)
        if existing is None:
            raise ValueError(f"Manual review record not found: {review_id}")

        video_id = str(existing["video_id"])
        video = conn.execute(
            "SELECT path, width, height, duration_s, fps_nominal FROM videos WHERE video_id = ?",
            (video_id,),
        ).fetchone()
        if video is None:
            raise ValueError(f"Associated video not found: {video_id}")

        video_path = Path(video["path"])
        if not video_path.is_absolute():
            video_path = repo_root / video_path

        out_dir = Path(review_cfg.get("output_dir", "data/processed/review_snippets"))
        if not out_dir.is_absolute():
            out_dir = repo_root / out_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        snippet_file = out_dir / f"snippet_{review_id}.mp4"

        created_path = create_snippet_file(
            video_path=video_path,
            timestamp_s=float(existing["timestamp_s"]),
            output_path=snippet_file,
            before_s=float(review_cfg.get("snippet_before_s", 1.0)),
            after_s=float(review_cfg.get("snippet_after_s", 1.0)),
            duration_s=float(video["duration_s"]) if video["duration_s"] is not None else None,
            width=int(video["width"]) if video["width"] is not None else None,
            height=int(video["height"]) if video["height"] is not None else None,
            fps=float(video["fps_nominal"]) if video["fps_nominal"] else 30.0,
        )

        update_manual_review_record(
            conn,
            review_id,
            {"snippet_path": str(created_path), "reviewed_at": _utc_now()},
        )
        conn.commit()

        return created_path

    if connection is not None:
        return _execute(connection)

    with database_connection(db_path) as conn:
        return _execute(conn)


def create_snippet_file(
    video_path: Path,
    timestamp_s: float,
    output_path: Path,
    before_s: float = 1.0,
    after_s: float = 1.0,
    duration_s: float | None = None,
    width: int | None = None,
    height: int | None = None,
    fps: float = 30.0,
) -> Path:
    """Extract before/after video snippet spanning [start_s, end_s]."""
    if not video_path.is_file():
        raise FileNotFoundError(f"Source video file does not exist: {video_path}")

    start_s, end_s = compute_snippet_window(
        timestamp_s=timestamp_s,
        duration_s=duration_s,
        before_s=before_s,
        after_s=after_s,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output_path = output_path.with_name(f"{output_path.stem}.tmp{output_path.suffix}")

    v_width = width or 1280
    v_height = height or 720
    v_fps = fps or 30.0

    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(temp_output_path), fourcc, v_fps, (v_width, v_height))
    if not writer.isOpened():
        raise RuntimeError(f"Unable to open VideoWriter for {temp_output_path}")

    frames_written = 0
    try:
        for _frame_idx, pts, rgb_frame in iter_decoded_images(video_path):
            if pts < start_s:
                continue
            if pts > end_s:
                break
            bgr_frame = cv2.cvtColor(rgb_frame, cv2.COLOR_RGB2BGR)
            if bgr_frame.shape[1] != v_width or bgr_frame.shape[0] != v_height:
                bgr_frame = cv2.resize(bgr_frame, (v_width, v_height))
            writer.write(bgr_frame)
            frames_written += 1
    finally:
        writer.release()

    if frames_written == 0:
        # If no frames matched within pts window (e.g. PTS decoding gap), create blank clip
        blank = np.zeros((v_height, v_width, 3), dtype=np.uint8)
        fallback_writer = cv2.VideoWriter(str(temp_output_path), fourcc, v_fps, (v_width, v_height))
        fallback_writer.write(blank)
        fallback_writer.release()

    if temp_output_path.exists():
        temp_output_path.replace(output_path)

    return output_path
