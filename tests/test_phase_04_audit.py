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
    """Verify behavior when observations from multiple runs share the same track_id."""
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
    # Because grouping is by track_id alone, rows from run-A and run-B get pooled
    # and then flagged as STATUS_INVALID due to inconsistent run_id.
    trajs = build_trajectories(rows)
    assert 1 in trajs
    assert trajs[1].status == STATUS_INVALID
    assert "Inconsistent run_id" in trajs[1].status_reason


def test_audit_active_status_precedence_over_internal_gaps() -> None:
    """Demonstrates that a track with a huge internal gap touching the final frame is classified as 'active' instead of 'fragmented'."""
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

    # When last_video_frame == 100, status becomes STATUS_ACTIVE despite 9.9s gap
    trajs = build_trajectories(rows, last_video_frame=100)
    # Finding: status is active even though there is a massive internal gap
    assert trajs[100].status == STATUS_ACTIVE
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

    # Check midpoint (60, 60): cv2.polylines drew a straight line across the unobserved gap!
    # Non-zero pixels exist between (20,20) and (100,100)
    assert np.any(rendered[55:65, 55:65] > 0)


def test_audit_zero_area_bounding_box() -> None:
    """Check behavior on zero-area degenerate bounding box (x1 == x2, y1 == y2)."""
    gx, gy = compute_ground_point(50.0, 50.0, 50.0, 50.0, method="bottom_center")
    assert gx == 50.0
    assert gy == 50.0
