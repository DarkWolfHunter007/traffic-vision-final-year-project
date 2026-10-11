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
