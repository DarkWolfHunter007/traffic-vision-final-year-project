"""Phase 09 unit tests for stopped vehicle and queue detection pure logic.

All test fixtures in this module are synthetic software fixtures, explicitly
labelled as such. No real-world research measurements or calibration points
are fabricated.
"""

from __future__ import annotations

import math
from typing import Any
from uuid import uuid4

import cv2
import numpy as np
import pytest

from backend.calibration import project_image_to_world
from backend.config import ConfigError, load_config
from backend.queue import (
    STATUS_INVALID,
    STATUS_UNAVAILABLE,
    STATUS_VALID,
    QueueEvent,
    StopEvent,
    compute_queue_length_m,
    detect_queue_events_at_timestamp,
    detect_stop_events_for_track,
    detect_stop_events_for_tracks,
    evaluate_queue_events_for_run,
    point_in_polygon,
)
from backend.speed import SpeedObservation
from backend.trajectories import Trajectory, TrajectoryPoint

# Clearly labelled synthetic software test fixtures
SOFTWARE_FIXTURE_IMAGE_PTS = np.array(
    [
        [200.0, 500.0],
        [600.0, 500.0],
        [500.0, 200.0],
        [300.0, 200.0],
    ],
    dtype=np.float64,
)
SOFTWARE_FIXTURE_WORLD_PTS = np.array(
    [
        [0.0, 0.0],
        [10.0, 0.0],
        [10.0, 30.0],
        [0.0, 30.0],
    ],
    dtype=np.float64,
)
SOFTWARE_FIXTURE_H, _ = cv2.findHomography(
    SOFTWARE_FIXTURE_IMAGE_PTS, SOFTWARE_FIXTURE_WORLD_PTS
)


def _make_obs(timestamp_s: float, speed_kmh: float | None, status: str = STATUS_VALID, track_id: int = 1) -> dict[str, Any]:
    """Helper creating synthetic observation dictionary."""
    return {
        "speed_observation_id": str(uuid4()),
        "run_id": "synthetic_run_01",
        "video_id": "synthetic_vid_01",
        "track_id": track_id,
        "timestamp_s": float(timestamp_s),
        "speed_kmh": speed_kmh,
        "speed_mps": speed_kmh / 3.6 if speed_kmh is not None else None,
        "calibration_id": "synthetic_calib_01",
        "status": status,
        "smoothing_window": 0.5,
        "ground_point_method": "bottom_center",
    }


def test_tp9_01_speed_threshold_boundary() -> None:
    """TP9-01: Vehicle speeds <= stop_speed_threshold_kmh are classified as stopped; speeds above are moving."""
    threshold = 5.0
    # Stop episode at exactly threshold (5.0 km/h) sustained for 3.0 s -> confirmed
    obs_at_threshold = [
        _make_obs(0.0, 5.0),
        _make_obs(1.0, 5.0),
        _make_obs(2.0, 5.0),
        _make_obs(3.0, 5.0),
    ]
    stops = detect_stop_events_for_track(1, obs_at_threshold, stop_speed_threshold_kmh=threshold, min_stop_duration_s=3.0)
    assert len(stops) == 1
    assert stops[0].status == STATUS_VALID
    assert stops[0].duration_s == 3.0

    # Speeds just above threshold (5.1 km/h) -> moving, no stop confirmed
    obs_above_threshold = [
        _make_obs(0.0, 5.1),
        _make_obs(1.0, 5.1),
        _make_obs(2.0, 5.1),
        _make_obs(3.0, 5.1),
    ]
    stops_above = detect_stop_events_for_track(1, obs_above_threshold, stop_speed_threshold_kmh=threshold, min_stop_duration_s=3.0)
    assert len(stops_above) == 0


def test_tp9_02_duration_accumulation() -> None:
    """TP9-02: Sustained stops >= min_stop_duration_s produce confirmed stop_events; shorter stops are not persisted."""
    min_dur = 3.0
    # Sustained stop for 3.5 seconds
    obs_sustained = [
        _make_obs(0.0, 1.0),
        _make_obs(1.0, 0.5),
        _make_obs(2.0, 0.0),
        _make_obs(3.0, 0.0),
        _make_obs(3.5, 0.0),
        _make_obs(4.0, 15.0),  # starts moving
    ]
    stops = detect_stop_events_for_track(1, obs_sustained, min_stop_duration_s=min_dur)
    assert len(stops) == 1
    assert stops[0].start_timestamp_s == 0.0
    assert stops[0].end_timestamp_s == 3.5
    assert stops[0].duration_s == 3.5
    assert stops[0].status == STATUS_VALID

    # Short stop for only 2.0 seconds (< 3.0 s)
    obs_short = [
        _make_obs(0.0, 0.0),
        _make_obs(1.0, 0.0),
        _make_obs(2.0, 0.0),
        _make_obs(2.5, 20.0),  # starts moving
    ]
    stops_short = detect_stop_events_for_track(1, obs_short, min_stop_duration_s=min_dur)
    assert len(stops_short) == 0


def test_tp9_03_temporal_gap_rule() -> None:
    """TP9-03: Temporal gaps exceeding max_gap_seconds break stopped continuity and split/terminate episodes."""
    # Track stopped from t=0 to t=4, then 2.0s gap, then stopped from t=6 to t=10
    obs_with_gap = [
        _make_obs(0.0, 0.0),
        _make_obs(1.0, 0.0),
        _make_obs(2.0, 0.0),
        _make_obs(3.0, 0.0),
        _make_obs(4.0, 0.0),
        # Gap of 2.0 s > max_gap_s (1.0 s)
        _make_obs(6.0, 0.0),
        _make_obs(7.0, 0.0),
        _make_obs(8.0, 0.0),
        _make_obs(9.0, 0.0),
        _make_obs(10.0, 0.0),
    ]
    stops = detect_stop_events_for_track(1, obs_with_gap, min_stop_duration_s=3.0, max_gap_s=1.0)
    assert len(stops) == 2
    assert stops[0].start_timestamp_s == 0.0
    assert stops[0].end_timestamp_s == 4.0
    assert stops[0].duration_s == 4.0

    assert stops[1].start_timestamp_s == 6.0
    assert stops[1].end_timestamp_s == 10.0
    assert stops[1].duration_s == 4.0

    # If post-gap episode is shorter than min_duration, only the first is confirmed
    obs_gap_short_second = [
        _make_obs(0.0, 0.0),
        _make_obs(1.0, 0.0),
        _make_obs(2.0, 0.0),
        _make_obs(3.0, 0.0),
        # Gap of 2.0 s
        _make_obs(5.0, 0.0),
        _make_obs(6.0, 0.0),  # only 1.0 s after gap
    ]
    stops_one = detect_stop_events_for_track(1, obs_gap_short_second, min_stop_duration_s=3.0, max_gap_s=1.0)
    assert len(stops_one) == 1
    assert stops_one[0].start_timestamp_s == 0.0
    assert stops_one[0].end_timestamp_s == 3.0


def test_tp9_04_non_monotonic_and_negative_dt_invalid() -> None:
    """TP9-04: Non-monotonic or negative intervals are flagged with status='invalid'."""
    # Negative time jump from t=3.0 to t=2.0
    obs_non_monotonic = [
        _make_obs(0.0, 0.0),
        _make_obs(1.0, 0.0),
        _make_obs(2.0, 0.0),
        _make_obs(3.0, 0.0),
        _make_obs(2.0, 0.0),  # non-monotonic (dt = -1.0)
    ]
    events = detect_stop_events_for_track(1, obs_non_monotonic, min_stop_duration_s=3.0)
    invalid_events = [e for e in events if e.status == STATUS_INVALID]
    assert len(invalid_events) >= 1
    assert invalid_events[0].start_timestamp_s == 2.0


def test_tp9_05_min_queue_vehicles_boundary() -> None:
    """TP9-05: Stopped vehicle counts < min_queue_vehicles record count but yield queue_length_m = 0.0 and status='valid'."""
    zone = {
        "zone_id": "zone_north_queue",
        "zone_type": "queue",
        "approach": "north",
        "vertices": [[0.0, 0.0], [500.0, 0.0], [500.0, 500.0], [0.0, 500.0]],
    }
    # Only 1 vehicle in queue zone (< min_queue_vehicles = 2)
    stopped_tracks = [{"track_id": 1, "ground_x": 100.0, "ground_y": 100.0}]
    q_events = detect_queue_events_at_timestamp(
        timestamp_s=1.0,
        stopped_tracks_at_t=stopped_tracks,
        zones=[zone],
        counting_lines=[],
        homography_matrix=np.eye(3),
        min_queue_vehicles=2,
    )
    assert len(q_events) == 1
    ev = q_events[0]
    assert ev.zone_id == "zone_north_queue"
    assert ev.queued_vehicle_count == 1
    assert ev.queue_length_m == 0.0
    assert ev.status == STATUS_VALID


def test_tp9_06_queue_formation_trigger() -> None:
    """TP9-06: Stopped vehicle counts >= min_queue_vehicles trigger queue formation and calculate non-zero queue length."""
    zone = {
        "zone_id": "zone_north_queue",
        "zone_type": "queue",
        "approach": "north",
        "vertices": [[0.0, 0.0], [500.0, 0.0], [500.0, 500.0], [0.0, 500.0]],
    }
    # 2 vehicles in zone (>= min_queue_vehicles = 2)
    stopped_tracks = [
        {"track_id": 1, "ground_x": 100.0, "ground_y": 100.0},
        {"track_id": 2, "ground_x": 100.0, "ground_y": 150.0},
    ]
    # Simple identity homography (1 pixel = 1 metre)
    q_events = detect_queue_events_at_timestamp(
        timestamp_s=1.0,
        stopped_tracks_at_t=stopped_tracks,
        zones=[zone],
        counting_lines=[],
        homography_matrix=np.eye(3),
        min_queue_vehicles=2,
    )
    assert len(q_events) == 1
    ev = q_events[0]
    assert ev.queued_vehicle_count == 2
    assert ev.queue_length_m == pytest.approx(50.0, rel=1e-3)
    assert ev.status == STATUS_VALID


def test_tp9_07_queue_zone_spatial_containment() -> None:
    """TP9-07: Only vehicles whose bottom-centre ground contact point lies inside the queue zone polygon are counted."""
    zone = {
        "zone_id": "zone_queue_box",
        "zone_type": "queue",
        "approach": "north",
        "vertices": [[100.0, 100.0], [300.0, 100.0], [300.0, 300.0], [100.0, 300.0]],
    }
    # Vehicle 1 is inside [200, 200]
    # Vehicle 2 is inside [250, 250]
    # Vehicle 3 is outside [50, 50]
    # Vehicle 4 is outside [400, 200]
    stopped_tracks = [
        {"track_id": 1, "ground_x": 200.0, "ground_y": 200.0},
        {"track_id": 2, "ground_x": 250.0, "ground_y": 250.0},
        {"track_id": 3, "ground_x": 50.0, "ground_y": 50.0},
        {"track_id": 4, "ground_x": 400.0, "ground_y": 200.0},
    ]
    q_events = detect_queue_events_at_timestamp(
        timestamp_s=2.0,
        stopped_tracks_at_t=stopped_tracks,
        zones=[zone],
        counting_lines=[],
        homography_matrix=np.eye(3),
        min_queue_vehicles=2,
    )
    assert len(q_events) == 1
    assert q_events[0].queued_vehicle_count == 2


def test_tp9_08_calibrated_world_coordinate_queue_length() -> None:
    """TP9-08: Queue length is computed in metres from calibrated world coordinates (X, Y) using accepted homography."""
    # Test using SOFTWARE_FIXTURE_H
    # Image points [200, 500] and [600, 500] project to [0, 0] and [10, 0] world (distance = 10.0 metres)
    zone = {
        "zone_id": "zone_test",
        "zone_type": "queue",
        "approach": "north",
        "vertices": [[100.0, 100.0], [700.0, 100.0], [700.0, 600.0], [100.0, 600.0]],
    }
    stopped_tracks = [
        {"track_id": 1, "ground_x": 200.0, "ground_y": 500.0},
        {"track_id": 2, "ground_x": 600.0, "ground_y": 500.0},
    ]
    q_events = detect_queue_events_at_timestamp(
        timestamp_s=1.0,
        stopped_tracks_at_t=stopped_tracks,
        zones=[zone],
        counting_lines=[],
        homography_matrix=SOFTWARE_FIXTURE_H,
        min_queue_vehicles=2,
    )
    assert len(q_events) == 1
    # Physical span in world is exactly 10.0 metres
    assert q_events[0].queue_length_m == pytest.approx(10.0, rel=1e-3)
    assert q_events[0].status == STATUS_VALID


def test_tp9_09_uncalibrated_input_and_no_pixel_fallback() -> None:
    """TP9-09: Missing calibration sets queue_length_m = None and status = 'unavailable'; pixel fallback is strictly prohibited."""
    zone = {
        "zone_id": "zone_uncalib",
        "zone_type": "queue",
        "approach": "north",
        "vertices": [[0.0, 0.0], [500.0, 0.0], [500.0, 500.0], [0.0, 500.0]],
    }
    stopped_tracks = [
        {"track_id": 1, "ground_x": 100.0, "ground_y": 100.0},
        {"track_id": 2, "ground_x": 200.0, "ground_y": 200.0},
    ]
    q_events = detect_queue_events_at_timestamp(
        timestamp_s=1.0,
        stopped_tracks_at_t=stopped_tracks,
        zones=[zone],
        counting_lines=[],
        homography_matrix=None,  # No calibration available
        min_queue_vehicles=2,
    )
    assert len(q_events) == 1
    assert q_events[0].queue_length_m is None
    assert q_events[0].status == STATUS_UNAVAILABLE
    assert q_events[0].queued_vehicle_count == 2


def test_tp9_10_stop_line_distance_and_ordering() -> None:
    """TP9-10: Queue length from a stop line measures the physical distance to the rear-most queued vehicle."""
    # Stop line from (0, 0) to (10, 0)
    # Vehicle 1 at (5, 5) -> distance 5m
    # Vehicle 2 at (5, 12) -> distance 12m
    # Vehicle 3 at (5, 20) -> distance 20m (furthest / rear-most)
    pts_world = [[5.0, 5.0], [5.0, 12.0], [5.0, 20.0]]
    stop_line_world = [[0.0, 0.0], [10.0, 0.0]]
    length = compute_queue_length_m(pts_world, stop_line_world=stop_line_world)
    assert length == pytest.approx(20.0, rel=1e-3)

    # Without stop line: max pairwise distance between (5, 5) and (5, 20) is 15.0m
    span = compute_queue_length_m(pts_world, stop_line_world=None)
    assert span == pytest.approx(15.0, rel=1e-3)


def test_tp9_11_aggregation_interval_time_slicing() -> None:
    """TP9-11: Queue state is evaluated at regular intervals governed by aggregation_interval_s."""
    zone = {
        "zone_id": "zone_1",
        "zone_type": "queue",
        "approach": "north",
        "vertices": [[0.0, 0.0], [500.0, 0.0], [500.0, 500.0], [0.0, 500.0]],
    }
    # Vehicle track 1 and 2 stopped continuously from t=0.0 to t=5.0
def _make_point(frame_number: int, timestamp_s: float, ground_x: float, ground_y: float) -> TrajectoryPoint:
    return TrajectoryPoint(
        frame_number=frame_number,
        timestamp_s=timestamp_s,
        ground_x=ground_x,
        ground_y=ground_y,
        x1=ground_x - 10.0,
        y1=ground_y - 20.0,
        x2=ground_x + 10.0,
        y2=ground_y,
        confidence=0.9,
        vehicle_class="car",
    )


def _make_trajectory(track_id: int, points: list[TrajectoryPoint], video_id: str = "vid_1") -> Trajectory:
    return Trajectory(
        run_id="run_1",
        video_id=video_id,
        track_id=track_id,
        points=points,
        consensus_class="car",
        status="complete",
        status_reason="normal",
        total_observations=len(points),
        missing_frames_count=0,
        duration_s=points[-1].timestamp_s - points[0].timestamp_s if points else 0.0,
        is_incomplete=False,
    )


def test_tp9_11_aggregation_interval_time_slicing() -> None:
    """TP9-11: Queue state is evaluated at regular intervals governed by aggregation_interval_s."""
    zone = {
        "zone_id": "zone_1",
        "zone_type": "queue",
        "approach": "north",
        "vertices": [[0.0, 0.0], [500.0, 0.0], [500.0, 500.0], [0.0, 500.0]],
    }
    # Vehicle track 1 and 2 stopped continuously from t=0.0 to t=5.0
    obs_t1 = [_make_obs(float(t), 0.0, track_id=1) for t in range(6)]
    obs_t2 = [_make_obs(float(t), 0.0, track_id=2) for t in range(6)]
    all_obs = obs_t1 + obs_t2

    pts1 = [_make_point(t, float(t), 100.0, 100.0) for t in range(6)]
    pts2 = [_make_point(t, float(t), 100.0, 150.0) for t in range(6)]
    trajectories = {
        1: _make_trajectory(1, pts1),
        2: _make_trajectory(2, pts2),
    }

    # Evaluate with aggregation_interval_s = 2.0 -> sample instants: 0.0, 2.0, 4.0
    config = {
        "queue": {
            "aggregation_interval_s": 2.0,
            "min_stop_duration_s": 3.0,
            "min_queue_vehicles": 2,
        }
    }
    stop_events, queue_events = evaluate_queue_events_for_run(
        speed_observations=all_obs,
        trajectories=trajectories,
        zones=[zone],
        counting_lines=[],
        homography_matrix=np.eye(3),
        config=config,
    )
    assert len(stop_events) == 2
    timestamps = [qe.timestamp_s for qe in queue_events]
    assert timestamps == [0.0, 2.0, 4.0]


def test_tp9_14_config_validation_enforces_queue_parameters() -> None:
    """TP9-14: Config validation enforces all queue parameters and value constraints."""
    # Valid default config loads without error
    cfg = load_config()
    assert cfg["queue"]["stop_speed_threshold_kmh"] == 5.0
    assert cfg["queue"]["min_stop_duration_s"] == 3.0
    assert cfg["queue"]["min_queue_vehicles"] == 2
    assert cfg["queue"]["aggregation_interval_s"] == 1.0
    assert cfg["queue"]["max_gap_seconds"] == 1.0
    assert isinstance(cfg["queue"]["stop_line_mapping"], dict)

    # Negative stop speed threshold
    with pytest.raises(ConfigError, match="queue.stop_speed_threshold_kmh"):
        load_config(overrides={"queue": {"stop_speed_threshold_kmh": -1.0}})

    # Negative stop duration
    with pytest.raises(ConfigError, match="queue.min_stop_duration_s"):
        load_config(overrides={"queue": {"min_stop_duration_s": -0.5}})

    # min_queue_vehicles < 1
    with pytest.raises(ConfigError, match="queue.min_queue_vehicles"):
        load_config(overrides={"queue": {"min_queue_vehicles": 0}})

    # aggregation_interval_s <= 0
    with pytest.raises(ConfigError, match="queue.aggregation_interval_s"):
        load_config(overrides={"queue": {"aggregation_interval_s": 0.0}})

    # max_gap_seconds <= 0
    with pytest.raises(ConfigError, match="queue.max_gap_seconds"):
        load_config(overrides={"queue": {"max_gap_seconds": 0.0}})


def test_tp9_16_signal_phase_independence() -> None:
    """TP9-16: Queue detection operates independently of external signal phase timing."""
    # Queue detection runs without requiring any signal phase parameters or external telemetry
    zone = {
        "zone_id": "zone_1",
        "zone_type": "queue",
        "approach": "north",
        "vertices": [[0.0, 0.0], [500.0, 0.0], [500.0, 500.0], [0.0, 500.0]],
    }
    obs_t1 = [_make_obs(float(t), 0.0, track_id=1) for t in range(4)]
    obs_t2 = [_make_obs(float(t), 0.0, track_id=2) for t in range(4)]
    pts1 = [_make_point(t, float(t), 100.0, 100.0) for t in range(4)]
    pts2 = [_make_point(t, float(t), 100.0, 150.0) for t in range(4)]
    trajectories = {
        1: _make_trajectory(1, pts1),
        2: _make_trajectory(2, pts2),
    }

    stops, queues = evaluate_queue_events_for_run(
        speed_observations=obs_t1 + obs_t2,
        trajectories=trajectories,
        zones=[zone],
        counting_lines=[],
        homography_matrix=np.eye(3),
        config=None,
    )
    assert len(stops) == 2
    assert len(queues) == 4
    for q in queues:
        assert q.status == STATUS_VALID
        assert q.queued_vehicle_count == 2


def test_point_in_polygon_ray_casting() -> None:
    """Verify ray-casting point-in-polygon containment on convex and concave shapes."""
    # Simple rectangle [0, 0] to [10, 10]
    rect = [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]
    assert point_in_polygon(5.0, 5.0, rect) is True
    assert point_in_polygon(15.0, 5.0, rect) is False
    assert point_in_polygon(-1.0, 5.0, rect) is False

    # Triangle
    tri = [[0.0, 0.0], [10.0, 0.0], [5.0, 10.0]]
    assert point_in_polygon(5.0, 2.0, tri) is True
    assert point_in_polygon(1.0, 8.0, tri) is False

    # Fewer than 3 vertices -> False
    assert point_in_polygon(5.0, 5.0, [[0.0, 0.0], [10.0, 0.0]]) is False


def test_compute_queue_length_m_edge_cases() -> None:
    """Verify compute_queue_length_m edge cases and robustness."""
    # Empty points
    assert compute_queue_length_m([]) == 0.0

    # Single point without stop line
    assert compute_queue_length_m([[5.0, 5.0]]) == 0.0

    # Single point with stop line point
    assert compute_queue_length_m([[5.0, 5.0]], stop_line_world=[0.0, 0.0]) == pytest.approx(math.hypot(5.0, 5.0))

    # Non-finite coordinates
    assert compute_queue_length_m([[float("nan"), 5.0]]) is None
    assert compute_queue_length_m([[5.0, 5.0]], stop_line_world=[float("inf"), 0.0]) is None
