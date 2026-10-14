"""Phase 08 unit tests for calibrated speed estimation pure logic.

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

from backend.calibration import project_world_to_image
from backend.config import ConfigError, load_config
from backend.speed import (
    STATUS_INVALID,
    STATUS_UNAVAILABLE,
    STATUS_VALID,
    SpeedObservation,
    estimate_speeds_for_trajectories,
    estimate_speeds_for_trajectory,
    kmh_to_mps,
    mps_to_kmh,
    smooth_trajectory_positions,
)
from backend.trajectories import (
    STATUS_COMPLETE,
    STATUS_INVALID as TRAJ_STATUS_INVALID,
    Trajectory,
    TrajectoryPoint,
)

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
SOFTWARE_FIXTURE_H_INV = np.linalg.inv(SOFTWARE_FIXTURE_H)


def _make_trajectory_point_from_world(
    frame_number: int,
    timestamp_s: float,
    world_x: float,
    world_y: float,
    box_width: float = 40.0,
    box_height: float = 80.0,
) -> TrajectoryPoint:
    """Helper creating a TrajectoryPoint whose bottom-centre maps to world (world_x, world_y)."""
    img_u, img_v = project_world_to_image(world_x, world_y, SOFTWARE_FIXTURE_H_INV)
    x1 = img_u - box_width / 2.0
    x2 = img_u + box_width / 2.0
    y1 = img_v - box_height
    y2 = img_v  # bottom-center ground_y is y2, ground_x is (x1 + x2)/2 = img_u
    return TrajectoryPoint(
        frame_number=frame_number,
        timestamp_s=timestamp_s,
        ground_x=img_u,
        ground_y=img_v,
        x1=x1,
        y1=y1,
        x2=x2,
        y2=y2,
        confidence=0.9,
        vehicle_class="car",
    )


def test_tp8_01_unit_conversions() -> None:
    """TP8-01: Unit conversions between m/s and km/h are exact and reversible."""
    assert mps_to_kmh(0.0) == 0.0
    assert mps_to_kmh(10.0) == 36.0
    assert mps_to_kmh(25.0) == 90.0
    assert abs(mps_to_kmh(100.0 / 3.6) - 100.0) < 1e-3
    assert kmh_to_mps(36.0) == 10.0
    assert kmh_to_mps(90.0) == 25.0
    assert kmh_to_mps(0.0) == 0.0

    # Reversibility
    speed_mps = 13.8889  # ~50 km/h
    kmh = mps_to_kmh(speed_mps)
    back_mps = kmh_to_mps(kmh)
    assert abs(back_mps - speed_mps) < 1e-3


def test_tp8_02_constant_velocity_matches_ground_truth() -> None:
    """TP8-02: Synthetic vehicle moving at known constant velocity yields exact speed."""
    calib_id = "software_calib_001"
    run_id = "software_run_001"
    # Vehicle moving along Y axis at 10.0 m/s (36.0 km/h) with dt = 0.1s
    # In each step, delta Y = 1.0 m, delta t = 0.1s => speed = 10.0 m/s
    points = [
        _make_trajectory_point_from_world(fn, fn * 0.1, 5.0, fn * 1.0)
        for fn in range(10)
    ]
    traj = Trajectory(
        run_id=run_id,
        video_id="software_vid_001",
        track_id=1,
        points=points,
        consensus_class="car",
        status=STATUS_COMPLETE,
        status_reason="boundary_exit",
        total_observations=len(points),
        missing_frames_count=0,
        duration_s=0.9,
        is_incomplete=False,
    )

    # Disable smoothing for exact instantaneous test
    cfg = {"speed": {"smoothing_method": "none", "min_track_points": 3}}
    observations = estimate_speeds_for_trajectory(
        trajectory=traj,
        homography_matrix=SOFTWARE_FIXTURE_H,
        calibration_id=calib_id,
        run_id=run_id,
        config=cfg,
    )

    assert len(observations) == 10

    # Initial point has status unavailable
    assert observations[0].status == STATUS_UNAVAILABLE
    assert observations[0].speed_mps is None
    assert observations[0].speed_kmh is None

    # Intermediate and final observations match 10.0 m/s (36.0 km/h)
    for obs in observations[1:]:
        assert obs.status == STATUS_VALID
        assert obs.speed_mps is not None
        assert abs(obs.speed_mps - 10.0) < 0.05
        assert obs.speed_kmh is not None
        assert abs(obs.speed_kmh - 36.0) < 0.18


def test_tp8_03_authoritative_timestamps_vs_nominal_fps() -> None:
    """TP8-03: Speed uses authoritative timestamps (PTS) rather than nominal FPS."""
    calib_id = "software_calib_001"
    run_id = "software_run_001"

    # 3 observations moving 1 metre between consecutive frames
    # Case A: dt = 0.05s (e.g. 20 Hz capture) => 1m / 0.05s = 20 m/s (72 km/h)
    pts_a = [
        _make_trajectory_point_from_world(0, 0.0, 5.0, 0.0),
        _make_trajectory_point_from_world(1, 0.05, 5.0, 1.0),
        _make_trajectory_point_from_world(2, 0.10, 5.0, 2.0),
    ]
    # Case B: dt = 0.20s (e.g. 5 Hz capture) => 1m / 0.20s = 5 m/s (18 km/h)
    pts_b = [
        _make_trajectory_point_from_world(0, 0.0, 5.0, 0.0),
        _make_trajectory_point_from_world(1, 0.20, 5.0, 1.0),
        _make_trajectory_point_from_world(2, 0.40, 5.0, 2.0),
    ]

    traj_a = Trajectory(
        run_id=run_id, video_id="vid", track_id=1, points=pts_a,
        consensus_class="car", status=STATUS_COMPLETE, status_reason="exit",
        total_observations=3, missing_frames_count=0, duration_s=0.10, is_incomplete=False,
    )
    traj_b = Trajectory(
        run_id=run_id, video_id="vid", track_id=2, points=pts_b,
        consensus_class="car", status=STATUS_COMPLETE, status_reason="exit",
        total_observations=3, missing_frames_count=0, duration_s=0.40, is_incomplete=False,
    )

    cfg = {"speed": {"smoothing_method": "none"}}
    obs_a = estimate_speeds_for_trajectory(traj_a, SOFTWARE_FIXTURE_H, calib_id, run_id, cfg)
    obs_b = estimate_speeds_for_trajectory(traj_b, SOFTWARE_FIXTURE_H, calib_id, run_id, cfg)

    # Both have frame interval = 1 frame, but speed is derived from pts_s
    assert abs(obs_a[1].speed_mps - 20.0) < 0.1  # type: ignore[operator]
    assert abs(obs_b[1].speed_mps - 5.0) < 0.1   # type: ignore[operator]


def test_tp8_04_initial_point_status_unavailable() -> None:
    """TP8-04: First point of a track has no preceding interval and is marked unavailable."""
    calib_id = "software_calib_001"
    run_id = "software_run_001"
    points = [
        _make_trajectory_point_from_world(0, 0.0, 5.0, 0.0),
        _make_trajectory_point_from_world(1, 0.1, 5.0, 1.0),
        _make_trajectory_point_from_world(2, 0.2, 5.0, 2.0),
    ]
    traj = Trajectory(
        run_id=run_id, video_id="vid", track_id=1, points=points,
        consensus_class="car", status=STATUS_COMPLETE, status_reason="exit",
        total_observations=3, missing_frames_count=0, duration_s=0.2, is_incomplete=False,
    )
    obs = estimate_speeds_for_trajectory(traj, SOFTWARE_FIXTURE_H, calib_id, run_id)
    assert obs[0].status == STATUS_UNAVAILABLE
    assert obs[0].speed_mps is None
    assert obs[0].speed_kmh is None
    assert obs[0].world_x is not None
    assert obs[0].world_y is not None


def test_tp8_05_timestamp_gap_rule() -> None:
    """TP8-05: Consecutive points with temporal gap > max_gap_seconds are marked unavailable."""
    calib_id = "software_calib_001"
    run_id = "software_run_001"
    # Observation 0: t=0.0
    # Observation 1: t=0.1 (continuous)
    # Observation 2: t=2.0 (1.9s gap > 1.0s)
    # Observation 3: t=2.1 (continuous again)
    points = [
        _make_trajectory_point_from_world(0, 0.0, 5.0, 0.0),
        _make_trajectory_point_from_world(1, 0.1, 5.0, 1.0),
        _make_trajectory_point_from_world(2, 2.0, 5.0, 5.0),
        _make_trajectory_point_from_world(3, 2.1, 5.0, 6.0),
    ]
    traj = Trajectory(
        run_id=run_id, video_id="vid", track_id=1, points=points,
        consensus_class="car", status=STATUS_COMPLETE, status_reason="exit",
        total_observations=4, missing_frames_count=19, duration_s=2.1, is_incomplete=False,
    )
    cfg = {"speed": {"smoothing_method": "none", "max_gap_seconds": 1.0}}
    obs = estimate_speeds_for_trajectory(traj, SOFTWARE_FIXTURE_H, calib_id, run_id, cfg)

    assert obs[0].status == STATUS_UNAVAILABLE  # initial
    assert obs[1].status == STATUS_VALID        # continuous
    assert obs[2].status == STATUS_UNAVAILABLE  # across gap
    assert obs[2].speed_mps is None
    assert obs[3].status == STATUS_VALID        # continuous after gap
    assert abs(obs[3].speed_mps - 10.0) < 0.1   # type: ignore[operator]


def test_tp8_06_non_monotonic_and_zero_dt_marked_invalid() -> None:
    """TP8-06: Non-monotonic or duplicate timestamps (dt <= 0) produce status='invalid'."""
    calib_id = "software_calib_001"
    run_id = "software_run_001"
    points = [
        _make_trajectory_point_from_world(0, 1.0, 5.0, 0.0),
        _make_trajectory_point_from_world(1, 1.0, 5.0, 1.0),  # dt = 0.0 duplicate timestamp
        _make_trajectory_point_from_world(2, 0.5, 5.0, 2.0),  # dt = -0.5 backwards timestamp
        _make_trajectory_point_from_world(3, 1.5, 5.0, 3.0),
    ]
    traj = Trajectory(
        run_id=run_id, video_id="vid", track_id=1, points=points,
        consensus_class="car", status=STATUS_COMPLETE, status_reason="exit",
        total_observations=4, missing_frames_count=0, duration_s=0.5, is_incomplete=False,
    )
    obs = estimate_speeds_for_trajectory(traj, SOFTWARE_FIXTURE_H, calib_id, run_id)
    assert obs[1].status == STATUS_INVALID
    assert obs[1].speed_mps is None
    assert obs[2].status == STATUS_INVALID
    assert obs[2].speed_mps is None


def test_tp8_07_short_tracks_marked_unavailable() -> None:
    """TP8-07: Tracks with fewer than min_track_points are marked unavailable."""
    calib_id = "software_calib_001"
    run_id = "software_run_001"
    points = [
        _make_trajectory_point_from_world(0, 0.0, 5.0, 0.0),
        _make_trajectory_point_from_world(1, 0.1, 5.0, 1.0),
    ]  # only 2 points, default min_track_points=3
    traj = Trajectory(
        run_id=run_id, video_id="vid", track_id=1, points=points,
        consensus_class="car", status=STATUS_COMPLETE, status_reason="exit",
        total_observations=2, missing_frames_count=0, duration_s=0.1, is_incomplete=False,
    )
    cfg = {"speed": {"min_track_points": 3}}
    obs = estimate_speeds_for_trajectory(traj, SOFTWARE_FIXTURE_H, calib_id, run_id, cfg)
    assert len(obs) == 2
    assert obs[0].status == STATUS_UNAVAILABLE
    assert obs[1].status == STATUS_UNAVAILABLE
    assert obs[1].speed_mps is None


def test_tp8_08_stationary_vehicle_and_jitter_filtering() -> None:
    """TP8-08: Sub-threshold displacement (< min_displacement_m) gives valid speed 0.0 m/s."""
    calib_id = "software_calib_001"
    run_id = "software_run_001"
    # Vehicle stationary at (5.0, 10.0), tiny position jitter of 0.02m (< min_displacement_m = 0.1m)
    points = [
        _make_trajectory_point_from_world(0, 0.0, 5.0, 10.0),
        _make_trajectory_point_from_world(1, 0.1, 5.01, 10.01),
        _make_trajectory_point_from_world(2, 0.2, 5.0, 10.0),
    ]
    traj = Trajectory(
        run_id=run_id, video_id="vid", track_id=1, points=points,
        consensus_class="car", status=STATUS_COMPLETE, status_reason="exit",
        total_observations=3, missing_frames_count=0, duration_s=0.2, is_incomplete=False,
    )
    cfg = {"speed": {"min_displacement_m": 0.10, "smoothing_method": "none"}}
    obs = estimate_speeds_for_trajectory(traj, SOFTWARE_FIXTURE_H, calib_id, run_id, cfg)

    assert obs[1].status == STATUS_VALID
    assert obs[1].speed_mps == 0.0
    assert obs[1].speed_kmh == 0.0
    assert obs[2].status == STATUS_VALID
    assert obs[2].speed_mps == 0.0
    assert obs[2].speed_kmh == 0.0


def test_tp8_09_implausible_speed_outlier_rejection() -> None:
    """TP8-09: Speeds exceeding max_plausible_speed_mps are rejected as invalid."""
    calib_id = "software_calib_001"
    run_id = "software_run_001"
    # Vehicle jumps 10 metres in 0.1s => 100 m/s (360 km/h) > cutoff (45 m/s)
    points = [
        _make_trajectory_point_from_world(0, 0.0, 5.0, 0.0),
        _make_trajectory_point_from_world(1, 0.1, 5.0, 10.0),
        _make_trajectory_point_from_world(2, 0.2, 5.0, 20.0),
    ]
    traj = Trajectory(
        run_id=run_id, video_id="vid", track_id=1, points=points,
        consensus_class="car", status=STATUS_COMPLETE, status_reason="exit",
        total_observations=3, missing_frames_count=0, duration_s=0.2, is_incomplete=False,
    )
    cfg = {"speed": {"max_plausible_speed_mps": 45.0, "smoothing_method": "none"}}
    obs = estimate_speeds_for_trajectory(traj, SOFTWARE_FIXTURE_H, calib_id, run_id, cfg)

    assert obs[1].status == STATUS_INVALID
    assert obs[1].speed_mps is None
    assert obs[1].speed_kmh is None


def test_tp8_10_deterministic_position_smoothing() -> None:
    """TP8-10: Centered moving average smoothing smooths noisy position coordinates."""
    # Synthetic trajectory with zero-mean alternating position jitter
    raw_tuples = [
        (0.0, 5.0, 0.0),
        (0.1, 5.2, 1.0),
        (0.2, 4.8, 2.0),
        (0.3, 5.2, 3.0),
        (0.4, 4.8, 4.0),
        (0.5, 5.0, 5.0),
    ]
    smoothed = smooth_trajectory_positions(raw_tuples, window_s=0.3, max_gap_s=1.0)
    assert len(smoothed) == len(raw_tuples)

    # In the interior, X coordinates should average out closer to 5.0 than raw extremes (5.2 / 4.8)
    for idx in range(1, 5):
        sm_x = smoothed[idx][0]
        assert abs(sm_x - 5.0) < 0.15


def test_uncalibrated_point_projection_failure_marked_invalid() -> None:
    """Test uncalibrated point (projection failure) is marked invalid."""
    calib_id = "software_calib_001"
    run_id = "software_run_001"
    # Second point has non-finite ground_x (NaN)
    p0 = _make_trajectory_point_from_world(0, 0.0, 5.0, 0.0)
    p1 = TrajectoryPoint(
        frame_number=1, timestamp_s=0.1,
        ground_x=float("nan"), ground_y=200.0,
        x1=0.0, y1=0.0, x2=10.0, y2=200.0,
    )
    p2 = _make_trajectory_point_from_world(2, 0.2, 5.0, 2.0)
    traj = Trajectory(
        run_id=run_id, video_id="vid", track_id=1, points=[p0, p1, p2],
        consensus_class="car", status=STATUS_COMPLETE, status_reason="exit",
        total_observations=3, missing_frames_count=0, duration_s=0.2, is_incomplete=False,
    )
    obs = estimate_speeds_for_trajectory(traj, SOFTWARE_FIXTURE_H, calib_id, run_id)
    assert obs[1].status == STATUS_INVALID
    assert obs[1].speed_mps is None


def test_invalid_trajectory_status_marked_invalid() -> None:
    """Test trajectory marked invalid results in all observations being invalid."""
    calib_id = "software_calib_001"
    run_id = "software_run_001"
    points = [
        _make_trajectory_point_from_world(0, 0.0, 5.0, 0.0),
        _make_trajectory_point_from_world(1, 0.1, 5.0, 1.0),
        _make_trajectory_point_from_world(2, 0.2, 5.0, 2.0),
    ]
    traj = Trajectory(
        run_id=run_id, video_id="vid", track_id=1, points=points,
        consensus_class="car", status=TRAJ_STATUS_INVALID, status_reason="corrupt",
        total_observations=3, missing_frames_count=0, duration_s=0.2, is_incomplete=False,
    )
    obs = estimate_speeds_for_trajectory(traj, SOFTWARE_FIXTURE_H, calib_id, run_id)
    for o in obs:
        assert o.status == STATUS_INVALID
        assert o.speed_mps is None


def test_tp8_14_config_validation_enforces_constraints() -> None:
    """TP8-14: Config loader validates speed configuration constraints."""
    # Valid config loads fine
    cfg = load_config()
    assert "speed" in cfg
    assert cfg["speed"]["smoothing_method"] == "moving_average"
    assert cfg["speed"]["smoothing_window_s"] == 0.5
    assert cfg["speed"]["min_track_points"] == 3

    # Invalid smoothing_method
    with pytest.raises(ConfigError, match="speed.smoothing_method"):
        load_config(overrides={"speed": {"smoothing_method": "kalman_invalid"}})

    # Negative smoothing_window_s
    with pytest.raises(ConfigError, match="speed.smoothing_window_s"):
        load_config(overrides={"speed": {"smoothing_window_s": -1.0}})

    # min_track_points < 2
    with pytest.raises(ConfigError, match="speed.min_track_points"):
        load_config(overrides={"speed": {"min_track_points": 1}})

    # Non-positive max_gap_seconds
    with pytest.raises(ConfigError, match="speed.max_gap_seconds"):
        load_config(overrides={"speed": {"max_gap_seconds": 0.0}})

    # Negative min_displacement_m
    with pytest.raises(ConfigError, match="speed.min_displacement_m"):
        load_config(overrides={"speed": {"min_displacement_m": -0.1}})

    # Invalid ground_point_method (must be bottom_center)
    with pytest.raises(ConfigError, match="speed.ground_point_method"):
        load_config(overrides={"speed": {"ground_point_method": "center"}})


# ---------------------------------------------------------------------------
# Phase 08 defect-fix value-checking tests (synthetic software fixtures)
# ---------------------------------------------------------------------------


def _traj_from_world(samples: list[tuple[float, float, float]], track_id: int = 1) -> Trajectory:
    points = [
        _make_trajectory_point_from_world(i, t, x, y) for i, (t, x, y) in enumerate(samples)
    ]
    return Trajectory(
        run_id="software_run",
        video_id="vid",
        track_id=track_id,
        points=points,
        consensus_class="car",
        status=STATUS_COMPLETE,
        status_reason="exit",
        total_observations=len(points),
        missing_frames_count=0,
        duration_s=samples[-1][0] - samples[0][0],
        is_incomplete=False,
    )


def _run(traj: Trajectory, cfg: dict[str, Any] | None = None) -> list[SpeedObservation]:
    return estimate_speeds_for_trajectory(traj, SOFTWARE_FIXTURE_H, "calib", "run", cfg)


@pytest.mark.parametrize("fps", [10, 30, 60])
@pytest.mark.parametrize("count", [3, 4, 5, 6, 30, 90])
def test_d1_constant_velocity_exact_under_default_smoothing(fps: int, count: int) -> None:
    speed = 3.0
    samples = [(i / fps, 5.0, 1.0 + speed * i / fps) for i in range(count)]
    obs = _run(_traj_from_world(samples))
    assert obs[0].status == STATUS_UNAVAILABLE
    for o in obs[1:]:
        assert o.status == STATUS_VALID
        assert o.speed_mps == pytest.approx(speed, abs=1e-3)
        assert o.smoothing_window == 0.5


def test_d1_short_post_gap_segment_not_zero_for_moving_car() -> None:
    speed = 4.0
    times = [0.0, 0.1, 0.2, 0.3, 0.4, 2.0, 2.1, 2.2]
    samples = [(t, 5.0, 1.0 + speed * t) for t in times]
    obs = _run(_traj_from_world(samples))
    assert obs[5].status == STATUS_UNAVAILABLE and obs[5].speed_mps is None
    for o in obs[6:]:
        assert o.status == STATUS_VALID
        assert o.speed_mps == pytest.approx(speed, abs=1e-3)
    for o in obs[1:5]:
        assert o.speed_mps == pytest.approx(speed, abs=1e-3)


def test_d1_smoothing_never_bridges_gap_and_is_symmetric() -> None:
    pts = [(0.0, 0.0, 0.0), (0.1, 1.0, 0.0), (0.2, 2.0, 0.0), (5.0, 100.0, 0.0), (5.1, 101.0, 0.0)]
    out = smooth_trajectory_positions(pts, window_s=0.5, max_gap_s=1.0)
    assert out[1][0] == pytest.approx(1.0)  # symmetric average of 0,1,2
    assert out[3][0] == pytest.approx(100.0)  # not pulled toward pre-gap points
    assert out[4][0] == pytest.approx(101.0)


@pytest.mark.parametrize("fps", [10, 30, 60, 120])
def test_d2_two_mps_not_stationary_at_any_fps(fps: int) -> None:
    samples = [(i / fps, 5.0, 1.0 + 2.0 * i / fps) for i in range(fps)]
    obs = _run(_traj_from_world(samples), {"speed": {"smoothing_method": "none"}})
    for o in obs[1:]:
        assert o.status == STATUS_VALID
        assert o.speed_mps == pytest.approx(2.0, abs=1e-3)


@pytest.mark.parametrize("fps", [10, 30, 60, 120])
def test_d2_jitter_is_valid_zero_at_any_fps(fps: int) -> None:
    samples = [(i / fps, 5.0 + (0.02 if i % 2 else -0.02), 10.0 + (0.02 if i % 2 else -0.02)) for i in range(fps)]
    obs = _run(_traj_from_world(samples), {"speed": {"smoothing_method": "none"}})
    for o in obs[1:]:
        assert o.status == STATUS_VALID and o.speed_mps == 0.0 and o.speed_kmh == 0.0


@pytest.mark.parametrize("fps", [30, 60])
@pytest.mark.parametrize("smoothing", ["moving_average", "none"])
def test_n1_edge_jitter_yields_zero_including_first_and_last_steps(fps: int, smoothing: str) -> None:
    rng = np.random.default_rng(7)
    jit = rng.uniform(-0.03, 0.03, size=(2 * fps, 2))
    samples = [(i / fps, 5.0 + jit[i, 0], 10.0 + jit[i, 1]) for i in range(2 * fps)]
    # force worst-case alternating extremes at the segment edges
    samples[0] = (0.0, 5.0 - 0.03, 10.0 - 0.03)
    samples[1] = (1 / fps, 5.0 + 0.03, 10.0 + 0.03)
    samples[-2] = ((2 * fps - 2) / fps, 5.0 - 0.03, 10.0 - 0.03)
    samples[-1] = ((2 * fps - 1) / fps, 5.0 + 0.03, 10.0 + 0.03)
    obs = _run(_traj_from_world(samples), {"speed": {"smoothing_method": smoothing}})
    for o in obs[1:]:
        assert o.status == STATUS_VALID
        assert o.speed_mps == 0.0


def test_n1_real_slow_motion_preserved() -> None:
    samples = [(i / 30, 5.0, 10.0 + 0.3 * i / 30) for i in range(90)]
    obs = _run(_traj_from_world(samples))
    for o in obs[1:]:
        assert o.speed_mps == pytest.approx(0.3, abs=1e-3)


def test_d3_raw_spike_marks_affected_outputs_invalid() -> None:
    # 1 m/s steady with a single 20 m raw jump in one 30 fps step (600 m/s raw)
    samples = []
    for i in range(30):
        y = 1.0 + 0.03 * i + (0.0 if i < 15 else 2.0)
        samples.append((i / 30, 5.0, y))
    # Smoothed step speed would stay under 45 m/s, but the raw step is 60 m/s
    obs = _run(_traj_from_world(samples), {"speed": {"max_plausible_speed_mps": 45.0}})
    invalid = [o for o in obs if o.status == STATUS_INVALID]
    assert invalid, "spike must invalidate outputs whose window contains it"
    for o in invalid:
        assert o.speed_mps is None and o.speed_kmh is None
    # far from the spike the speed is still valid
    assert obs[3].status == STATUS_VALID
    assert obs[-1].status == STATUS_VALID


def test_d5_smoothing_window_null_when_not_applied() -> None:
    samples = [(i / 10, 5.0, 1.0 + i / 10) for i in range(6)]
    for cfg in (
        {"speed": {"smoothing_method": "none"}},
        {"speed": {"smoothing_window_s": 0.0}},
    ):
        assert all(o.smoothing_window is None for o in _run(_traj_from_world(samples), cfg))
    assert all(o.smoothing_window == 0.5 for o in _run(_traj_from_world(samples)))
