"""Tests for Phase 04 trajectory aggregation, ground-point geometry, and continuity classification.

Software fixture notice: Test fixtures are synthetic software fixtures for validating
invariants and error handling; they do not represent real-world CCTV footage validation.
"""

from __future__ import annotations

import math
import pytest

from backend.trajectories import (
    STATUS_ACTIVE,
    STATUS_COMPLETE,
    STATUS_FRAGMENTED,
    STATUS_INVALID,
    TrajectoryPoint,
    build_trajectories,
    compute_ground_point,
)


def test_compute_ground_point_bottom_center_calculation() -> None:
    gx, gy = compute_ground_point(10.0, 20.0, 30.0, 60.0, method="bottom_center")
    assert gx == 20.0  # (10 + 30) / 2
    assert gy == 60.0


def test_compute_ground_point_rejects_bbox_center_and_unsupported_methods() -> None:
    with pytest.raises(ValueError, match="bottom_center"):
        compute_ground_point(10.0, 20.0, 30.0, 60.0, method="center")

    with pytest.raises(ValueError, match="bottom_center"):
        compute_ground_point(10.0, 20.0, 30.0, 60.0, method="centroid")


def test_compute_ground_point_rejects_malformed_coordinates() -> None:
    with pytest.raises(ValueError, match="Malformed"):
        compute_ground_point(50.0, 20.0, 30.0, 60.0)  # x1 > x2

    with pytest.raises(ValueError, match="Malformed"):
        compute_ground_point(10.0, 70.0, 30.0, 60.0)  # y1 > y2

    with pytest.raises(ValueError, match="finite"):
        compute_ground_point(float("nan"), 20.0, 30.0, 60.0)

    with pytest.raises(ValueError, match="finite"):
        compute_ground_point(10.0, 20.0, float("inf"), 60.0)


def test_build_trajectories_deterministic_chronological_ordering() -> None:
    # Observations intentionally supplied out of order
    rows = [
        {
            "run_id": "run-1",
            "video_id": "vid-1",
            "track_id": 1,
            "frame_number": 5,
            "timestamp_s": 0.5,
            "vehicle_class": "car",
            "confidence": 0.8,
            "x1": 50,
            "y1": 50,
            "x2": 100,
            "y2": 100,
        },
        {
            "run_id": "run-1",
            "video_id": "vid-1",
            "track_id": 1,
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
            "track_id": 1,
            "frame_number": 3,
            "timestamp_s": 0.3,
            "vehicle_class": "car",
            "confidence": 0.85,
            "x1": 30,
            "y1": 30,
            "x2": 70,
            "y2": 70,
        },
    ]

    trajs = build_trajectories(rows)
    assert 1 in trajs
    traj = trajs[1]
    assert [p.frame_number for p in traj.points] == [1, 3, 5]
    assert [p.timestamp_s for p in traj.points] == [0.1, 0.3, 0.5]
    assert traj.start_frame == 1
    assert traj.end_frame == 5


def test_build_trajectories_preserves_raw_observations_without_interpolation() -> None:
    # Gap between frame 2 and frame 6; intermediate frames 3, 4, 5 must NOT be invented
    rows = [
        {
            "run_id": "run-1",
            "video_id": "vid-1",
            "track_id": 2,
            "frame_number": 2,
            "timestamp_s": 0.2,
            "vehicle_class": "bus",
            "confidence": 0.9,
            "x1": 10,
            "y1": 10,
            "x2": 50,
            "y2": 50,
        },
        {
            "run_id": "run-1",
            "video_id": "vid-1",
            "track_id": 2,
            "frame_number": 6,
            "timestamp_s": 0.6,
            "vehicle_class": "bus",
            "confidence": 0.88,
            "x1": 60,
            "y1": 60,
            "x2": 100,
            "y2": 100,
        },
    ]

    trajs = build_trajectories(rows)
    traj = trajs[2]
    assert len(traj.points) == 2  # No fabricated points
    assert traj.missing_frames_count == 3  # Frames 3, 4, 5 missing


def test_build_trajectories_class_consensus_integration() -> None:
    # 2 motorcycle detections (conf 0.9, 0.85), 1 car detection (conf 0.6)
    rows = [
        {
            "run_id": "run-1",
            "video_id": "vid-1",
            "track_id": 5,
            "frame_number": 1,
            "timestamp_s": 0.1,
            "vehicle_class": "motorcycle",
            "confidence": 0.9,
            "x1": 10,
            "y1": 10,
            "x2": 30,
            "y2": 30,
        },
        {
            "run_id": "run-1",
            "video_id": "vid-1",
            "track_id": 5,
            "frame_number": 2,
            "timestamp_s": 0.2,
            "vehicle_class": "car",
            "confidence": 0.6,
            "x1": 12,
            "y1": 12,
            "x2": 32,
            "y2": 32,
        },
        {
            "run_id": "run-1",
            "video_id": "vid-1",
            "track_id": 5,
            "frame_number": 3,
            "timestamp_s": 0.3,
            "vehicle_class": "motorcycle",
            "confidence": 0.85,
            "x1": 15,
            "y1": 15,
            "x2": 35,
            "y2": 35,
        },
    ]

    trajs = build_trajectories(rows)
    traj = trajs[5]
    # Consensus class should be motorcycle by confidence-weighted voting
    assert traj.consensus_class == "motorcycle"
    # Individual point classes must remain preserved as originally detected
    assert traj.points[1].vehicle_class == "car"


def test_build_trajectories_status_active() -> None:
    rows = [
        {
            "run_id": "run-1",
            "video_id": "vid-1",
            "track_id": 10,
            "frame_number": 98,
            "timestamp_s": 9.8,
            "vehicle_class": "auto_rickshaw",
            "confidence": 0.8,
            "x1": 100,
            "y1": 100,
            "x2": 150,
            "y2": 150,
        },
        {
            "run_id": "run-1",
            "video_id": "vid-1",
            "track_id": 10,
            "frame_number": 99,
            "timestamp_s": 9.9,
            "vehicle_class": "auto_rickshaw",
            "confidence": 0.82,
            "x1": 105,
            "y1": 105,
            "x2": 155,
            "y2": 155,
        },
        {
            "run_id": "run-1",
            "video_id": "vid-1",
            "track_id": 10,
            "frame_number": 100,
            "timestamp_s": 10.0,
            "vehicle_class": "auto_rickshaw",
            "confidence": 0.85,
            "x1": 110,
            "y1": 110,
            "x2": 160,
            "y2": 160,
        },
    ]

    # When last_video_frame is 100, track ending at 100 is classified as active
    trajs = build_trajectories(rows, last_video_frame=100)
    assert trajs[10].status == STATUS_ACTIVE
    assert trajs[10].is_incomplete is True


def test_build_trajectories_status_complete_exiting_boundary() -> None:
    # Video 1920x1080. Track starts inside and moves to boundary (x2=1915, within 20px margin)
    rows = [
        {
            "run_id": "run-1",
            "video_id": "vid-1",
            "track_id": 20,
            "frame_number": 10,
            "timestamp_s": 1.0,
            "vehicle_class": "car",
            "confidence": 0.9,
            "x1": 500,
            "y1": 400,
            "x2": 600,
            "y2": 500,
        },
        {
            "run_id": "run-1",
            "video_id": "vid-1",
            "track_id": 20,
            "frame_number": 11,
            "timestamp_s": 1.1,
            "vehicle_class": "car",
            "confidence": 0.9,
            "x1": 1000,
            "y1": 400,
            "x2": 1100,
            "y2": 500,
        },
        {
            "run_id": "run-1",
            "video_id": "vid-1",
            "track_id": 20,
            "frame_number": 12,
            "timestamp_s": 1.2,
            "vehicle_class": "car",
            "confidence": 0.9,
            "x1": 1850,
            "y1": 400,
            "x2": 1915,
            "y2": 500,
        },
    ]

    trajs = build_trajectories(rows, video_width=1920, video_height=1080, last_video_frame=200)
    assert trajs[20].status == STATUS_COMPLETE
    assert trajs[20].is_incomplete is False
    assert trajs[20].diagnostics["exited_boundary"] is True


def test_build_trajectories_status_fragmented_on_prolonged_gap() -> None:
    # Gap of 2.0 seconds exceeds max_gap_seconds=1.0
    rows = [
        {
            "run_id": "run-1",
            "video_id": "vid-1",
            "track_id": 30,
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
            "run_id": "run-1",
            "video_id": "vid-1",
            "track_id": 30,
            "frame_number": 2,
            "timestamp_s": 0.2,
            "vehicle_class": "car",
            "confidence": 0.8,
            "x1": 15,
            "y1": 15,
            "x2": 55,
            "y2": 55,
        },
        {
            "run_id": "run-1",
            "video_id": "vid-1",
            "track_id": 30,
            "frame_number": 25,
            "timestamp_s": 2.5,
            "vehicle_class": "car",
            "confidence": 0.8,
            "x1": 20,
            "y1": 20,
            "x2": 60,
            "y2": 60,
        },
    ]

    trajs = build_trajectories(rows, config={"trajectories": {"max_gap_seconds": 1.0}})
    assert trajs[30].status == STATUS_FRAGMENTED
    assert trajs[30].diagnostics["suspected_fragmentation"] is True
    assert len(trajs[30].diagnostics["internal_gaps"]) == 1


def test_build_trajectories_status_fragmented_on_interior_termination() -> None:
    # Track terminates in scene interior (x=500..600, y=400..500) well before frame 200
    rows = [
        {
            "run_id": "run-1",
            "video_id": "vid-1",
            "track_id": 35,
            "frame_number": 10,
            "timestamp_s": 1.0,
            "vehicle_class": "car",
            "confidence": 0.8,
            "x1": 500,
            "y1": 400,
            "x2": 550,
            "y2": 450,
        },
        {
            "run_id": "run-1",
            "video_id": "vid-1",
            "track_id": 35,
            "frame_number": 11,
            "timestamp_s": 1.1,
            "vehicle_class": "car",
            "confidence": 0.8,
            "x1": 510,
            "y1": 410,
            "x2": 560,
            "y2": 460,
        },
        {
            "run_id": "run-1",
            "video_id": "vid-1",
            "track_id": 35,
            "frame_number": 12,
            "timestamp_s": 1.2,
            "vehicle_class": "car",
            "confidence": 0.8,
            "x1": 520,
            "y1": 420,
            "x2": 570,
            "y2": 470,
        },
    ]

    trajs = build_trajectories(rows, video_width=1920, video_height=1080, last_video_frame=200)
    assert trajs[35].status == STATUS_FRAGMENTED
    assert trajs[35].diagnostics["exited_boundary"] is False


def test_build_trajectories_status_invalid_on_malformed_box() -> None:
    rows = [
        {
            "run_id": "run-1",
            "video_id": "vid-1",
            "track_id": 40,
            "frame_number": 1,
            "timestamp_s": 0.1,
            "vehicle_class": "car",
            "confidence": 0.8,
            "x1": 100,
            "y1": 50,
            "x2": 50,  # x1 > x2: malformed!
            "y2": 100,
        }
    ]

    trajs = build_trajectories(rows)
    assert trajs[40].status == STATUS_INVALID
    assert "Invalid bounding box" in trajs[40].status_reason


def test_build_trajectories_status_invalid_on_duplicate_frame() -> None:
    rows = [
        {
            "run_id": "run-1",
            "video_id": "vid-1",
            "track_id": 50,
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
            "run_id": "run-1",
            "video_id": "vid-1",
            "track_id": 50,
            "frame_number": 1,  # Duplicate frame_number 1
            "timestamp_s": 0.1,
            "vehicle_class": "car",
            "confidence": 0.75,
            "x1": 12,
            "y1": 12,
            "x2": 52,
            "y2": 52,
        },
    ]

    trajs = build_trajectories(rows)
    assert trajs[50].status == STATUS_INVALID
    assert "Duplicate observation" in trajs[50].status_reason


def test_build_trajectories_status_invalid_on_non_monotonic_timestamp() -> None:
    rows = [
        {
            "run_id": "run-1",
            "video_id": "vid-1",
            "track_id": 60,
            "frame_number": 1,
            "timestamp_s": 0.5,
            "vehicle_class": "car",
            "confidence": 0.8,
            "x1": 10,
            "y1": 10,
            "x2": 50,
            "y2": 50,
        },
        {
            "run_id": "run-1",
            "video_id": "vid-1",
            "track_id": 60,
            "frame_number": 2,
            "timestamp_s": 0.2,  # Non-monotonic: decreased from 0.5s to 0.2s!
            "vehicle_class": "car",
            "confidence": 0.8,
            "x1": 12,
            "y1": 12,
            "x2": 52,
            "y2": 52,
        },
    ]

    trajs = build_trajectories(rows)
    assert trajs[60].status == STATUS_INVALID
    assert "Non-monotonic timestamp" in trajs[60].status_reason


def test_build_trajectories_empty_and_trail_helpers() -> None:
    assert build_trajectories([]) == {}

    rows = [
        {
            "run_id": "run-1",
            "video_id": "vid-1",
            "track_id": 70,
            "frame_number": 1,
            "timestamp_s": 0.1,
            "vehicle_class": "car",
            "confidence": 0.8,
            "x1": 10,
            "y1": 10,
            "x2": 30,
            "y2": 40,
        },
        {
            "run_id": "run-1",
            "video_id": "vid-1",
            "track_id": 70,
            "frame_number": 2,
            "timestamp_s": 0.2,
            "vehicle_class": "car",
            "confidence": 0.8,
            "x1": 20,
            "y1": 20,
            "x2": 40,
            "y2": 50,
        },
    ]
    trajs = build_trajectories(rows)
    traj = trajs[70]
    # Check trail_points slicing
    assert len(traj.trail_points()) == 2
    assert len(traj.trail_points(max_length=1)) == 1
    assert traj.point_at_frame(1) is not None
    assert traj.point_at_frame(99) is None
