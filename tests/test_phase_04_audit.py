"""Temporary audit-only test suite for Phase 04 independent validation.

Probes boundary conditions, heuristic limitations, and potential edge-case failures
identified during the Phase 04 technical audit.
"""

from __future__ import annotations

import math
from pathlib import Path
import pytest
import numpy as np

from backend.trajectories import (
    STATUS_ACTIVE,
    STATUS_COMPLETE,
    STATUS_FRAGMENTED,
    STATUS_INVALID,
    Trajectory,
    TrajectoryPoint,
    build_trajectories,
    compute_ground_point,
)
from backend.visualization import (
    VisualizationConfig,
    render_frame_annotations,
)


def test_audit_cross_run_track_id_collision() -> None:
    """Verify that observations spanning multiple runs are rejected immediately."""
    rows = [
        {
            "run_id": "run-A",
            "video_id": "vid-1",
            "track_id": 1,
            "frame_number": 1,
            "timestamp_s": 0.1,
            "vehicle_class": "car",
            "confidence": 0.8,
            "x1": 10,
            "y1": 10,
            "x2": 50,
            "y2": 50,
        },
        {
            "run_id": "run-B",
            "video_id": "vid-1",
            "track_id": 1,
            "frame_number": 2,
            "timestamp_s": 0.2,
            "vehicle_class": "car",
            "confidence": 0.8,
            "x1": 15,
            "y1": 15,
            "x2": 55,
            "y2": 55,
        },
    ]
    with pytest.raises(ValueError, match="multiple runs"):
        build_trajectories(rows)


def test_audit_active_status_precedence_over_internal_gaps() -> None:
    """Verify that a track with an internal gap is marked fragmented/discontinuous even if active on final frame."""
    rows = [
        {
            "run_id": "run-1",
            "video_id": "vid-1",
            "track_id": 100,
            "frame_number": 1,
            "timestamp_s": 0.1,
            "vehicle_class": "car",
            "confidence": 0.9,
            "x1": 10,
            "y1": 10,
            "x2": 40,
            "y2": 40,
        },
        {
            "run_id": "run-1",
            "video_id": "vid-1",
            "track_id": 100,
            "frame_number": 100,  # 98 missing frames, gap of 9.9 seconds!
            "timestamp_s": 10.0,
            "vehicle_class": "car",
            "confidence": 0.9,
            "x1": 200,
            "y1": 200,
            "x2": 240,
            "y2": 240,
        },
    ]

    # When last_video_frame == 100, continuity is discontinuous and status is STATUS_FRAGMENTED,
    # while lifecycle is accurately recorded as active on final video frame.
    trajs = build_trajectories(rows, last_video_frame=100)
    assert trajs[100].status == STATUS_FRAGMENTED
    assert trajs[100].continuity == "discontinuous"
    assert trajs[100].lifecycle == "active"
    assert trajs[100].termination_reason == "video_end"
    assert len(trajs[100].diagnostics["internal_gaps"]) == 1


def test_audit_motion_trail_connects_across_unobserved_gaps() -> None:
    """Demonstrates that motion trails interpolate across multi-second observation gaps."""
    p1 = TrajectoryPoint(
        frame_number=1,
        timestamp_s=0.1,
        ground_x=20.0,
        ground_y=20.0,
        x1=10.0,
        y1=10.0,
        x2=30.0,
        y2=20.0,
        confidence=0.9,
        vehicle_class="car",
    )
    p2 = TrajectoryPoint(
        frame_number=100,  # 99 frames later!
        timestamp_s=10.0,
        ground_x=100.0,
        ground_y=100.0,
        x1=90.0,
        y1=90.0,
        x2=110.0,
        y2=100.0,
        confidence=0.9,
        vehicle_class="car",
    )
    traj = Trajectory(
        run_id="run-1",
        video_id="vid-1",
        track_id=1,
        points=[p1, p2],
        consensus_class="car",
        status="fragmented",
        status_reason="gap",
        total_observations=2,
        missing_frames_count=98,
        duration_s=9.9,
        is_incomplete=True,
    )

    img = np.zeros((150, 150, 3), dtype=np.uint8)
    rendered = render_frame_annotations(
        img,
        100,
        [(traj, p2)],
        VisualizationConfig(show_boxes=False, show_labels=False, show_trails=True, draw_ground_point=False),
    )

    # Verified fix: No bridge rendered across the unobserved 9.9s gap!
    # Midpoint (55:65, 55:65) between (20,20) and (100,100) must remain blank.
    assert not np.any(rendered[55:65, 55:65] > 0)


def test_audit_motion_trail_short_continuous_gap_renders_trail() -> None:
    """Verify that normal continuous points within threshold render a trail."""
    p1 = TrajectoryPoint(
        frame_number=1,
        timestamp_s=0.1,
        ground_x=20.0,
        ground_y=20.0,
        x1=10.0,
        y1=10.0,
        x2=30.0,
        y2=20.0,
    )
    p2 = TrajectoryPoint(
        frame_number=2,
        timestamp_s=0.2,
        ground_x=40.0,
        ground_y=40.0,
        x1=30.0,
        y1=30.0,
        x2=50.0,
        y2=40.0,
    )
    traj = Trajectory(
        run_id="run-1",
        video_id="vid-1",
        track_id=1,
        points=[p1, p2],
        consensus_class="car",
        status="complete",
        status_reason="normal",
        total_observations=2,
        missing_frames_count=0,
        duration_s=0.1,
        is_incomplete=False,
    )
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    rendered = render_frame_annotations(
        img,
        2,
        [(traj, p2)],
        VisualizationConfig(show_boxes=False, show_labels=False, show_trails=True, draw_ground_point=False),
    )
    # Midpoint (30, 30) between (20,20) and (40,40) must have trail pixels
    assert np.any(rendered[28:32, 28:32] > 0)


def test_audit_motion_trail_intentional_frame_stride() -> None:
    """Verify that points matching intentional frame stride cadence render a continuous trail."""
    # Stride of 5 frames, 0.5s intervals (<= 1.0s max_trail_gap_seconds)
    p1 = TrajectoryPoint(frame_number=0, timestamp_s=0.0, ground_x=20.0, ground_y=20.0, x1=10, y1=10, x2=30, y2=20)
    p2 = TrajectoryPoint(frame_number=5, timestamp_s=0.5, ground_x=40.0, ground_y=40.0, x1=30, y1=30, x2=50, y2=40)
    p3 = TrajectoryPoint(frame_number=10, timestamp_s=1.0, ground_x=60.0, ground_y=60.0, x1=50, y1=50, x2=70, y2=60)
    traj = Trajectory(
        run_id="run-1",
        video_id="vid-1",
        track_id=1,
        points=[p1, p2, p3],
        consensus_class="car",
        status="complete",
        status_reason="normal",
        total_observations=3,
        missing_frames_count=0,
        duration_s=1.0,
        is_incomplete=False,
    )
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    rendered = render_frame_annotations(
        img,
        10,
        [(traj, p3)],
        VisualizationConfig(show_boxes=False, show_labels=False, show_trails=True, draw_ground_point=False, max_trail_gap_seconds=1.0),
    )
    # Trail is drawn continuously across stride-5 points
    assert np.any(rendered[28:32, 28:32] > 0)
    assert np.any(rendered[48:52, 48:52] > 0)


def test_audit_motion_trail_segments_around_gap() -> None:
    """Verify that continuous segments on either side of a gap are rendered, but no line bridges the gap."""
    # Segment 1: p1 -> p2 (t=0.0 -> 0.1)
    # Gap: t=0.1 -> 5.0 (4.9s gap)
    # Segment 2: p3 -> p4 (t=5.0 -> 5.1)
    p1 = TrajectoryPoint(frame_number=0, timestamp_s=0.0, ground_x=10.0, ground_y=10.0, x1=5, y1=5, x2=15, y2=10)
    p2 = TrajectoryPoint(frame_number=1, timestamp_s=0.1, ground_x=20.0, ground_y=20.0, x1=15, y1=15, x2=25, y2=20)
    p3 = TrajectoryPoint(frame_number=50, timestamp_s=5.0, ground_x=80.0, ground_y=80.0, x1=75, y1=75, x2=85, y2=80)
    p4 = TrajectoryPoint(frame_number=51, timestamp_s=5.1, ground_x=90.0, ground_y=90.0, x1=85, y1=85, x2=95, y2=90)
    traj = Trajectory(
        run_id="run-1",
        video_id="vid-1",
        track_id=1,
        points=[p1, p2, p3, p4],
        consensus_class="car",
        status="fragmented",
        status_reason="gap",
        total_observations=4,
        missing_frames_count=48,
        duration_s=5.1,
        is_incomplete=True,
    )
    img = np.zeros((120, 120, 3), dtype=np.uint8)
    rendered = render_frame_annotations(
        img,
        51,
        [(traj, p4)],
        VisualizationConfig(show_boxes=False, show_labels=False, show_trails=True, draw_ground_point=False, max_trail_gap_seconds=1.0),
    )
    # Segment 1 (10,10 to 20,20) has pixels
    assert np.any(rendered[14:16, 14:16] > 0)
    # Segment 2 (80,80 to 90,90) has pixels
    assert np.any(rendered[84:86, 84:86] > 0)
    # Gap between (20,20) and (80,80) has NO bridge pixels at midpoint (50,50)
    assert not np.any(rendered[45:55, 45:55] > 0)


def test_audit_zero_area_bounding_box() -> None:
    """Check behavior on zero-area degenerate bounding box (x1 == x2, y1 == y2)."""
    gx, gy = compute_ground_point(50.0, 50.0, 50.0, 50.0, method="bottom_center")
    assert gx == 50.0
    assert gy == 50.0


def test_audit_stride_aware_gap_accounting() -> None:
    """Verify that intentional frame_stride > 1 is not mislabeled as missed detections."""
    # Stride 5: frame numbers 0, 5, 10
    rows = [
        {"run_id": "run-1", "video_id": "vid-1", "track_id": 1, "frame_number": 0, "timestamp_s": 0.0, "x1": 10, "y1": 10, "x2": 30, "y2": 30},
        {"run_id": "run-1", "video_id": "vid-1", "track_id": 1, "frame_number": 5, "timestamp_s": 0.5, "x1": 20, "y1": 20, "x2": 40, "y2": 40},
        {"run_id": "run-1", "video_id": "vid-1", "track_id": 1, "frame_number": 10, "timestamp_s": 1.0, "x1": 30, "y1": 30, "x2": 50, "y2": 50},
    ]
    trajs = build_trajectories(rows, frame_stride=5)
    traj = trajs[1]
    # Under stride 5, there are 0 missing expected samples
    assert traj.missing_frames_count == 0
    assert traj.diagnostics["raw_missing_frames"] == 8
    assert traj.diagnostics["frame_stride"] == 5


def test_audit_corrupt_stored_ground_coordinates_rejected() -> None:
    """Verify that stored ground coordinates inconsistent with computed ground contact points are rejected."""
    rows = [
        {
            "run_id": "run-1",
            "video_id": "vid-1",
            "track_id": 1,
            "frame_number": 0,
            "timestamp_s": 0.0,
            "x1": 10.0,
            "y1": 10.0,
            "x2": 30.0,
            "y2": 40.0,
            "ground_x": 999.0,  # Corrupt! Should be (10+30)/2 = 20.0
            "ground_y": 40.0,
        }
    ]
    trajs = build_trajectories(rows)
    assert trajs[1].status == STATUS_INVALID
    assert "Corrupt stored ground coordinates" in trajs[1].status_reason


def test_audit_negative_and_nonfinite_timestamps_rejected() -> None:
    """Verify that negative, NaN, and infinite timestamps are rejected as STATUS_INVALID."""
    row_negative = [{"run_id": "r1", "video_id": "v1", "track_id": 1, "frame_number": 0, "timestamp_s": -0.5, "x1": 10, "y1": 10, "x2": 20, "y2": 20}]
    assert build_trajectories(row_negative)[1].status == STATUS_INVALID

    row_nan = [{"run_id": "r1", "video_id": "v1", "track_id": 1, "frame_number": 0, "timestamp_s": float("nan"), "x1": 10, "y1": 10, "x2": 20, "y2": 20}]
    assert build_trajectories(row_nan)[1].status == STATUS_INVALID

    row_inf = [{"run_id": "r1", "video_id": "v1", "track_id": 1, "frame_number": 0, "timestamp_s": float("inf"), "x1": 10, "y1": 10, "x2": 20, "y2": 20}]
    assert build_trajectories(row_inf)[1].status == STATUS_INVALID


def test_audit_interior_termination_semantics() -> None:
    """Verify interior termination status, continuity, lifecycle, and uncertainty diagnostics."""
    rows = [
        {"run_id": "r1", "video_id": "v1", "track_id": 2, "frame_number": 1, "timestamp_s": 0.1, "x1": 100, "y1": 100, "x2": 150, "y2": 150},
        {"run_id": "r1", "video_id": "v1", "track_id": 2, "frame_number": 2, "timestamp_s": 0.2, "x1": 105, "y1": 105, "x2": 155, "y2": 155},
        {"run_id": "r1", "video_id": "v1", "track_id": 2, "frame_number": 3, "timestamp_s": 0.3, "x1": 110, "y1": 110, "x2": 160, "y2": 160},
    ]
    # Video 1280x720, last frame 100. Track ends at frame 3 in the middle of the frame
    trajs = build_trajectories(rows, video_width=1280, video_height=720, last_video_frame=100)
    traj = trajs[2]
    assert traj.status == STATUS_FRAGMENTED
    assert traj.continuity == "continuous"  # No internal gaps!
    assert traj.lifecycle == "ended"
    assert traj.termination_reason == "interior_termination"
    assert "uncertainty_note" in traj.diagnostics


def test_audit_visualization_frame_range_validation(tmp_path: Path) -> None:
    """Verify that invalid frame ranges are rejected by visualization services."""
    from backend.services.visualization import (
        render_preview_visualization,
        render_video_visualization,
    )
    from backend.database.connection import bootstrap_database, database_connection

    db_path = tmp_path / "vis_val.sqlite3"
    bootstrap_database(db_path)
    cfg = {"paths": {"database_path": str(db_path)}}

    with pytest.raises(ValueError, match="preview frame_number must be >= 0"):
        render_preview_visualization("run-1", -5, cfg, tmp_path)

    with pytest.raises(ValueError, match="start_frame must be >= 0"):
        render_video_visualization("run-1", cfg, tmp_path, start_frame=-1)

    with pytest.raises(ValueError, match="cannot be greater than end_frame"):
        render_video_visualization("run-1", cfg, tmp_path, start_frame=50, end_frame=10)


def test_audit_one_frame_range_preview_and_video(tmp_path: Path) -> None:
    """T2: Test start_frame == end_frame for both preview and video rendering.

    Asserts: exactly 1 frame rendered, run status completed, frame count 1 recorded.
    """
    import subprocess
    import shutil
    import cv2
    import json
    from backend.services.visualization import (
        render_preview_visualization,
        render_video_visualization,
    )
    from backend.database.connection import bootstrap_database, database_connection
    from backend.database.repository import insert_tracks
    from backend.media import inspect_video, sha256_file
    from backend.config import load_config

    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is required for synthetic video fixture")

    syn_video = tmp_path / "syn_one_frame.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=160x120:r=10:d=1", "-pix_fmt", "yuv420p", str(syn_video)],
        check=True,
        capture_output=True,
    )

    db_path = tmp_path / "traffic_one_frame.sqlite3"
    bootstrap_database(db_path)
    video_meta = inspect_video(syn_video)
    video_sha = sha256_file(syn_video)

    with database_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO videos (video_id, filename, path, sha256, fps_nominal, width, height, duration_s, frame_count, ingested_at)
            VALUES ('vid-syn', 'syn.mp4', ?, ?, ?, ?, ?, ?, ?, '2026-10-11T00:00:00Z')
            """,
            (
                str(syn_video),
                video_sha,
                video_meta.fps_nominal,
                video_meta.width,
                video_meta.height,
                video_meta.duration_s,
                video_meta.frame_count,
            ),
        )
        conn.execute(
            """
            INSERT INTO processing_runs (run_id, video_id, config_hash, config_json, schema_version, code_version, source_video_sha256, started_at, status)
            VALUES ('track-run-syn', 'vid-syn', 'cfg1', '{}', '1.0.0', 'code1', ?, '2026-10-11T00:00:00Z', 'completed')
            """,
            (video_sha,),
        )
        insert_tracks(
            conn,
            [
                {
                    "track_observation_id": "obs-syn-1",
                    "run_id": "track-run-syn",
                    "video_id": "vid-syn",
                    "track_id": 1,
                    "frame_number": 2,
                    "timestamp_s": 0.2,
                    "vehicle_class": "car",
                    "confidence": 0.85,
                    "x1": 20,
                    "y1": 20,
                    "x2": 60,
                    "y2": 60,
                    "ground_x": 40,
                    "ground_y": 60,
                    "world_x": None,
                    "world_y": None,
                    "calibration_id": None,
                    "trajectory_status": "complete",
                }
            ],
        )

    config = load_config(overrides={"paths": {"database_path": str(db_path)}})

    # 1. Preview rendering for a single frame
    preview_out = render_preview_visualization(
        "track-run-syn",
        frame_number=2,
        config=config,
        repository_root=tmp_path,
    )
    assert preview_out.is_file()
    img = cv2.imread(str(preview_out))
    assert img is not None
    assert img.shape[:2] == (video_meta.height, video_meta.width)

    # 2. Video rendering where start_frame == end_frame (exactly 1 frame)
    out_video = tmp_path / "one_frame.mp4"
    vis_run_id = render_video_visualization(
        "track-run-syn",
        config,
        repository_root=tmp_path,
        output_path=out_video,
        start_frame=2,
        end_frame=2,
    )
    assert out_video.is_file()

    with database_connection(db_path) as conn:
        run_record = conn.execute(
            "SELECT status, notes FROM processing_runs WHERE run_id = ?",
            (vis_run_id,),
        ).fetchone()

    assert run_record is not None
    assert run_record["status"] == "completed"
    notes = json.loads(run_record["notes"])
    assert notes["rendered_frames"] == 1
    assert notes["start_frame"] == 2
    assert notes["end_frame"] == 2


def test_audit_trail_gap_exact_boundary() -> None:
    """T3: Gap of exactly max_trail_gap_seconds is joined; gap just over splits.

    Also tests the frames rule: gap of max_trail_gap_frames is joined; gap just over splits.
    """
    p1 = TrajectoryPoint(frame_number=0, timestamp_s=0.0, ground_x=20.0, ground_y=20.0, x1=10, y1=10, x2=30, y2=20)
    # Exact seconds boundary: dt = 1.0s -> joined
    p2_exact = TrajectoryPoint(frame_number=10, timestamp_s=1.0, ground_x=80.0, ground_y=80.0, x1=70, y1=70, x2=90, y2=80)
    traj_exact = Trajectory(
        run_id="r1", video_id="v1", track_id=1, points=[p1, p2_exact],
        consensus_class="car", status="complete", status_reason="ok",
        total_observations=2, missing_frames_count=9, duration_s=1.0, is_incomplete=False,
    )
    canvas = np.zeros((100, 100, 3), dtype=np.uint8)
    rendered_exact = render_frame_annotations(
        canvas, 10, [(traj_exact, p2_exact)],
        VisualizationConfig(show_boxes=False, show_labels=False, show_trails=True, draw_ground_point=False, max_trail_gap_seconds=1.0),
    )
    # Midpoint (50, 50) has trail pixels because 1.0s is NOT > 1.0s
    assert np.any(rendered_exact[48:52, 48:52] > 0)

    # Just over seconds boundary: dt = 1.001s -> splits
    p2_over = TrajectoryPoint(frame_number=10, timestamp_s=1.001, ground_x=80.0, ground_y=80.0, x1=70, y1=70, x2=90, y2=80)
    traj_over = Trajectory(
        run_id="r1", video_id="v1", track_id=2, points=[p1, p2_over],
        consensus_class="car", status="complete", status_reason="ok",
        total_observations=2, missing_frames_count=9, duration_s=1.001, is_incomplete=False,
    )
    canvas = np.zeros((100, 100, 3), dtype=np.uint8)
    rendered_over = render_frame_annotations(
        canvas, 10, [(traj_over, p2_over)],
        VisualizationConfig(show_boxes=False, show_labels=False, show_trails=True, draw_ground_point=False, max_trail_gap_seconds=1.0),
    )
    # Midpoint (50, 50) is blank because 1.001s > 1.0s
    assert not np.any(rendered_over[48:52, 48:52] > 0)

    # Frames rule: exact gap = 10 frames -> joined
    p_f1 = TrajectoryPoint(frame_number=0, timestamp_s=0.0, ground_x=20.0, ground_y=20.0, x1=10, y1=10, x2=30, y2=20)
    p_f2_exact = TrajectoryPoint(frame_number=10, timestamp_s=0.1, ground_x=80.0, ground_y=80.0, x1=70, y1=70, x2=90, y2=80)
    traj_f_exact = Trajectory(
        run_id="r1", video_id="v1", track_id=3, points=[p_f1, p_f2_exact],
        consensus_class="car", status="complete", status_reason="ok",
        total_observations=2, missing_frames_count=9, duration_s=0.1, is_incomplete=False,
    )
    canvas = np.zeros((100, 100, 3), dtype=np.uint8)
    rendered_f_exact = render_frame_annotations(
        canvas, 10, [(traj_f_exact, p_f2_exact)],
        VisualizationConfig(show_boxes=False, show_labels=False, show_trails=True, draw_ground_point=False, max_trail_gap_seconds=None, max_trail_gap_frames=10),
    )
    assert np.any(rendered_f_exact[48:52, 48:52] > 0)

    # Frames rule: just over gap = 11 frames -> splits
    p_f2_over = TrajectoryPoint(frame_number=11, timestamp_s=0.1, ground_x=80.0, ground_y=80.0, x1=70, y1=70, x2=90, y2=80)
    traj_f_over = Trajectory(
        run_id="r1", video_id="v1", track_id=4, points=[p_f1, p_f2_over],
        consensus_class="car", status="complete", status_reason="ok",
        total_observations=2, missing_frames_count=10, duration_s=0.1, is_incomplete=False,
    )
    canvas = np.zeros((100, 100, 3), dtype=np.uint8)
    rendered_f_over = render_frame_annotations(
        canvas, 11, [(traj_f_over, p_f2_over)],
        VisualizationConfig(show_boxes=False, show_labels=False, show_trails=True, draw_ground_point=False, max_trail_gap_seconds=None, max_trail_gap_frames=10),
    )
    assert not np.any(rendered_f_over[48:52, 48:52] > 0)


def test_audit_trail_gap_large_frame_stride_splits_all_samples() -> None:
    """T3: When frame_stride spacing causes dt > 1.0s between normal samples, trails split at every sample."""
    # Stride causes 1.5s between normal consecutive samples (0.0s, 1.5s, 3.0s)
    pts = [
        TrajectoryPoint(frame_number=0, timestamp_s=0.0, ground_x=20.0, ground_y=20.0, x1=10, y1=10, x2=30, y2=20),
        TrajectoryPoint(frame_number=15, timestamp_s=1.5, ground_x=50.0, ground_y=50.0, x1=40, y1=40, x2=60, y2=50),
        TrajectoryPoint(frame_number=30, timestamp_s=3.0, ground_x=80.0, ground_y=80.0, x1=70, y1=70, x2=90, y2=80),
    ]
    traj = Trajectory(
        run_id="r1", video_id="v1", track_id=1, points=pts,
        consensus_class="car", status="complete", status_reason="ok",
        total_observations=3, missing_frames_count=0, duration_s=3.0, is_incomplete=False,
    )
    canvas = np.zeros((100, 100, 3), dtype=np.uint8)
    # Default max_trail_gap_seconds=1.0
    rendered = render_frame_annotations(
        canvas, 30, [(traj, pts[-1])],
        VisualizationConfig(show_boxes=False, show_labels=False, show_ids=False, show_confidences=False, show_trails=True, draw_ground_point=False, max_trail_gap_seconds=1.0),
    )
    # Because dt=1.5s > 1.0s at each step, trails split at every single sample.
    # No multi-point segment exists, so canvas remains completely blank (0 trail pixels).
    assert not np.any(rendered > 0)


def test_audit_ground_point_tolerance() -> None:
    """T4: Stored ground_x/ground_y off by 0.0009 accepted, by 0.0011 rejected, for x and y separately."""
    base_row = {
        "run_id": "r1", "video_id": "v1", "track_id": 1,
        "frame_number": 0, "timestamp_s": 0.0,
        "x1": 10.0, "y1": 10.0, "x2": 30.0, "y2": 40.0,
    }

    # 1. ground_x off by +0.0009 -> Accepted (not invalid)
    row_x_acc = [dict(base_row, ground_x=20.0009, ground_y=40.0)]
    assert build_trajectories(row_x_acc)[1].status != STATUS_INVALID

    # 2. ground_y off by +0.0009 -> Accepted (not invalid)
    row_y_acc = [dict(base_row, ground_x=20.0, ground_y=40.0009)]
    assert build_trajectories(row_y_acc)[1].status != STATUS_INVALID

    # 3. ground_x off by +0.0011 -> Rejected (STATUS_INVALID)
    row_x_rej = [dict(base_row, ground_x=20.0011, ground_y=40.0)]
    t_x_rej = build_trajectories(row_x_rej)[1]
    assert t_x_rej.status == STATUS_INVALID
    assert "Corrupt stored ground coordinates" in t_x_rej.status_reason

    # 4. ground_y off by +0.0011 -> Rejected (STATUS_INVALID)
    row_y_rej = [dict(base_row, ground_x=20.0, ground_y=40.0011)]
    t_y_rej = build_trajectories(row_y_rej)[1]
    assert t_y_rej.status == STATUS_INVALID
    assert "Corrupt stored ground coordinates" in t_y_rej.status_reason


def test_audit_interior_termination_boundary_margin() -> None:
    """T5: Track ending exactly at margin_px (20.0), just inside, just outside: assert termination_reason."""
    # 1. Exactly at margin: x1 = 20.0 (x1 <= margin_px is True -> boundary_exit)
    rows_exact = [
        {"run_id": "r1", "video_id": "v1", "track_id": 1, "frame_number": 1, "timestamp_s": 0.1, "x1": 30.0, "y1": 100.0, "x2": 70.0, "y2": 150.0},
        {"run_id": "r1", "video_id": "v1", "track_id": 1, "frame_number": 2, "timestamp_s": 0.2, "x1": 25.0, "y1": 100.0, "x2": 65.0, "y2": 150.0},
        {"run_id": "r1", "video_id": "v1", "track_id": 1, "frame_number": 3, "timestamp_s": 0.3, "x1": 20.0, "y1": 100.0, "x2": 60.0, "y2": 150.0},
    ]
    t_exact = build_trajectories(rows_exact, video_width=1280, video_height=720, last_video_frame=100)[1]
    assert t_exact.termination_reason == "boundary_exit"
    assert t_exact.status == STATUS_COMPLETE

    # 2. Just inside margin (in boundary margin zone): x1 = 19.9 (x1 <= margin_px is True -> boundary_exit)
    rows_inside = [
        {"run_id": "r1", "video_id": "v1", "track_id": 2, "frame_number": 1, "timestamp_s": 0.1, "x1": 30.0, "y1": 100.0, "x2": 70.0, "y2": 150.0},
        {"run_id": "r1", "video_id": "v1", "track_id": 2, "frame_number": 2, "timestamp_s": 0.2, "x1": 25.0, "y1": 100.0, "x2": 65.0, "y2": 150.0},
        {"run_id": "r1", "video_id": "v1", "track_id": 2, "frame_number": 3, "timestamp_s": 0.3, "x1": 19.9, "y1": 100.0, "x2": 59.9, "y2": 150.0},
    ]
    t_inside = build_trajectories(rows_inside, video_width=1280, video_height=720, last_video_frame=100)[2]
    assert t_inside.termination_reason == "boundary_exit"
    assert t_inside.status == STATUS_COMPLETE

    # 3. Just outside margin (in scene interior): x1 = 20.1 (x1 <= margin_px is False -> interior_termination)
    rows_outside = [
        {"run_id": "r1", "video_id": "v1", "track_id": 3, "frame_number": 1, "timestamp_s": 0.1, "x1": 30.0, "y1": 100.0, "x2": 70.0, "y2": 150.0},
        {"run_id": "r1", "video_id": "v1", "track_id": 3, "frame_number": 2, "timestamp_s": 0.2, "x1": 25.0, "y1": 100.0, "x2": 65.0, "y2": 150.0},
        {"run_id": "r1", "video_id": "v1", "track_id": 3, "frame_number": 3, "timestamp_s": 0.3, "x1": 20.1, "y1": 100.0, "x2": 60.1, "y2": 150.0},
    ]
    t_outside = build_trajectories(rows_outside, video_width=1280, video_height=720, last_video_frame=100)[3]
    assert t_outside.termination_reason == "interior_termination"
    assert t_outside.status == STATUS_FRAGMENTED


def test_audit_stride_off_grid_gaps_current_behavior() -> None:
    """T6: Test frame gaps that are not multiples of stride (stride 5: gaps 7, 8, 12).

    Records current behavior:
    - Gap 7: round(7/5) = round(1.4) = 1 step -> missing_frames_count = 0 (undercounts: missed frame 5).
    - Gap 8: round(8/5) = round(1.6) = 2 steps -> missing_frames_count = 1.
    - Gap 12: round(12/5) = round(2.4) = 2 steps -> missing_frames_count = 1 (undercounts: missed frames 5 and 10).
    """
    # 1. Stride 5, Gap 7 (frames 0 and 7)
    rows_gap7 = [
        {"run_id": "r1", "video_id": "v1", "track_id": 1, "frame_number": 0, "timestamp_s": 0.0, "x1": 10, "y1": 10, "x2": 20, "y2": 20},
        {"run_id": "r1", "video_id": "v1", "track_id": 1, "frame_number": 7, "timestamp_s": 0.7, "x1": 30, "y1": 30, "x2": 40, "y2": 40},
    ]
    t7 = build_trajectories(rows_gap7, frame_stride=5)[1]
    assert t7.missing_frames_count == 0
    assert t7.diagnostics["raw_missing_frames"] == 6

    # 2. Stride 5, Gap 8 (frames 0 and 8)
    rows_gap8 = [
        {"run_id": "r1", "video_id": "v1", "track_id": 2, "frame_number": 0, "timestamp_s": 0.0, "x1": 10, "y1": 10, "x2": 20, "y2": 20},
        {"run_id": "r1", "video_id": "v1", "track_id": 2, "frame_number": 8, "timestamp_s": 0.8, "x1": 30, "y1": 30, "x2": 40, "y2": 40},
    ]
    t8 = build_trajectories(rows_gap8, frame_stride=5)[2]
    assert t8.missing_frames_count == 1
    assert t8.diagnostics["raw_missing_frames"] == 7

    # 3. Stride 5, Gap 12 (frames 0 and 12)
    rows_gap12 = [
        {"run_id": "r1", "video_id": "v1", "track_id": 3, "frame_number": 0, "timestamp_s": 0.0, "x1": 10, "y1": 10, "x2": 20, "y2": 20},
        {"run_id": "r1", "video_id": "v1", "track_id": 3, "frame_number": 12, "timestamp_s": 1.2, "x1": 30, "y1": 30, "x2": 40, "y2": 40},
    ]
    t12 = build_trajectories(rows_gap12, frame_stride=5)[3]
    assert t12.missing_frames_count == 1
    assert t12.diagnostics["raw_missing_frames"] == 11

