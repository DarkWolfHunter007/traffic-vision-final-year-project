"""Unit tests for Phase 06 pure counting, movement derivation, and aggregation logic.

All test fixtures are synthetic software test fixtures explicitly labelled as such.
"""

from __future__ import annotations

import pytest

from backend.counting import (
    aggregate_volume_bins,
    calculate_counting_comparison,
    derive_movement,
    detect_crossings_for_trajectory,
    point_in_polygon,
)
from backend.trajectories import Trajectory, TrajectoryPoint


def _create_software_fixture_trajectory(
    track_id: int,
    points_data: list[tuple[int, float, float, float]],
    consensus_class: str = "car",
    run_id: str = "run-fixture-01",
    video_id: str = "vid-fixture-01",
) -> Trajectory:
    """Create a Trajectory software test fixture for unit testing."""
    pts = [
        TrajectoryPoint(
            frame_number=fn,
            timestamp_s=ts,
            ground_x=gx,
            ground_y=gy,
            x1=gx - 20.0,
            y1=gy - 40.0,
            x2=gx + 20.0,
            y2=gy,
            confidence=0.9,
            vehicle_class=consensus_class,
        )
        for fn, ts, gx, gy in points_data
    ]
    return Trajectory(
        run_id=run_id,
        video_id=video_id,
        track_id=track_id,
        points=pts,
        consensus_class=consensus_class,
        status="complete",
        status_reason="Software fixture for counting tests",
        total_observations=len(pts),
        missing_frames_count=0,
        duration_s=(pts[-1].timestamp_s - pts[0].timestamp_s) if pts else 0.0,
        is_incomplete=False,
    )


def test_tp6_01_no_double_counting_and_deduplication() -> None:
    """TP6-01: No double counting: re-crossing within min_reentry_gap_s is flagged deduplicated=1."""
    # Line along y = 200 from (100, 200) to (500, 200), unidirectional downwards [0, 1]
    line = {
        "line_id": "line_north_entry",
        "approach": "north",
        "bidirectional": False,
        "config_version": "cfgver123456",
        "geometry_json": {
            "endpoints": [[100.0, 200.0], [500.0, 200.0]],
            "direction_vector": [0.0, 1.0],
        },
    }

    # Vehicle crosses y=200 downwards at t=1.0 (fn=10, y: 150->250),
    # then oscillates back up at t=1.5 (y: 250->150),
    # then re-crosses downwards at t=2.2 (< 2.0s reentry gap from first crossing at t=1.0)
    traj = _create_software_fixture_trajectory(
        track_id=101,
        points_data=[
            (0, 0.5, 300.0, 150.0),
            (10, 1.0, 300.0, 250.0),  # Crossing 1: downwards (valid, dedup=0)
            (15, 1.5, 300.0, 150.0),  # Crossing back: upwards (wrong-way on unidirectional, dedup=1)
            (22, 2.2, 300.0, 250.0),  # Crossing 2: downwards (< 2.0s gap from t=1.0, dedup=1)
            (35, 3.5, 300.0, 150.0),  # Upwards again (wrong-way, dedup=1)
            (40, 4.0, 300.0, 250.0),  # Crossing 3: downwards (> 2.0s gap from t=1.0, dedup=0)
        ],
    )

    crossings = detect_crossings_for_trajectory(
        trajectory=traj,
        counting_lines=[line],
        min_reentry_gap_s=2.0,
        max_gap_seconds=2.0,
    )

    # All raw crossing events are preserved!
    assert len(crossings) == 5

    # Event 0: initial valid crossing downwards
    assert crossings[0]["deduplicated"] == 0
    assert crossings[0]["direction"] == "forward"
    assert crossings[0]["timestamp_s"] == 1.0

    # Event 1: upwards (opposing direction vector)
    assert crossings[1]["deduplicated"] == 1
    assert crossings[1]["direction"] == "reverse"

    # Event 2: downwards re-entry within 2.0s gap (2.2 - 1.0 = 1.2s < 2.0s)
    assert crossings[2]["deduplicated"] == 1
    assert crossings[2]["direction"] == "forward"

    # Event 3: upwards again
    assert crossings[3]["deduplicated"] == 1
    assert crossings[3]["direction"] == "reverse"

    # Event 4: downwards re-entry after 2.0s gap (4.0 - 1.0 = 3.0s > 2.0s)
    assert crossings[4]["deduplicated"] == 0
    assert crossings[4]["direction"] == "forward"
    assert crossings[4]["timestamp_s"] == 4.0

    # When aggregated into volume bins, only deduplicated==0 are counted!
    bins = aggregate_volume_bins(crossings, run_id="run-1", video_id="vid-1", bin_duration_s=900.0)
    assert len(bins) == 1
    assert bins[0]["count"] == 2  # Only events 0 and 4 are counted


def test_tp6_02_bidirectional_lines_count_both_directions() -> None:
    """TP6-02: Bidirectional counting line counts valid crossings in both forward and reverse directions."""
    line = {
        "line_id": "line_bidirectional",
        "approach": "east",
        "bidirectional": True,
        "config_version": "cfgver123456",
        "geometry_json": {
            "endpoints": [[200.0, 100.0], [200.0, 500.0]],
            "direction_vector": None,
        },
    }

    # Track 1: moving left-to-right (x: 150 -> 250, across x=200)
    traj_forward = _create_software_fixture_trajectory(
        track_id=1,
        points_data=[
            (0, 0.0, 150.0, 300.0),
            (10, 1.0, 250.0, 300.0),
        ],
    )

    # Track 2: moving right-to-left (x: 250 -> 150, across x=200)
    traj_reverse = _create_software_fixture_trajectory(
        track_id=2,
        points_data=[
            (0, 2.0, 250.0, 300.0),
            (10, 3.0, 150.0, 300.0),
        ],
    )

    crossings_fwd = detect_crossings_for_trajectory(traj_forward, [line])
    crossings_rev = detect_crossings_for_trajectory(traj_reverse, [line])

    assert len(crossings_fwd) == 1
    assert crossings_fwd[0]["deduplicated"] == 0

    assert len(crossings_rev) == 1
    assert crossings_rev[0]["deduplicated"] == 0

    # Directions should be opposites
    assert crossings_fwd[0]["direction"] != crossings_rev[0]["direction"]

    # Both count towards volume bins
    all_crossings = crossings_fwd + crossings_rev
    bins = aggregate_volume_bins(all_crossings, run_id="run-1", video_id="vid-1", bin_duration_s=900.0)
    assert len(bins) == 1
    assert bins[0]["count"] == 2


def test_tp6_03_unidirectional_wrong_way_not_counted() -> None:
    """TP6-03: Unidirectional line honours direction_vector; opposing crossings are not counted in volume bins."""
    line = {
        "line_id": "line_south_unidirectional",
        "approach": "south",
        "bidirectional": False,
        "config_version": "cfgver123456",
        "geometry_json": {
            "endpoints": [[100.0, 300.0], [500.0, 300.0]],
            "direction_vector": [0.0, -1.0],  # Forward direction is northwards (y decreasing)
        },
    }

    # Track moving southwards (y increasing: 250 -> 350) => WRONG WAY
    traj_wrong_way = _create_software_fixture_trajectory(
        track_id=55,
        points_data=[
            (0, 0.0, 300.0, 250.0),
            (10, 1.0, 300.0, 350.0),
        ],
    )

    crossings = detect_crossings_for_trajectory(traj_wrong_way, [line])
    assert len(crossings) == 1
    # Raw event preserved, but flagged deduplicated=1 (not countable)
    assert crossings[0]["deduplicated"] == 1
    assert crossings[0]["direction"] == "reverse"

    # Volume bins aggregation counts 0
    bins = aggregate_volume_bins(crossings, run_id="run-1", video_id="vid-1", bin_duration_s=900.0)
    assert len(bins) == 0


def test_tp6_04_movement_derivation_and_unknown() -> None:
    """TP6-04: Movement derivation resolves left, through, right, u_turn from entry/exit zones; unresolved => unknown."""
    zones = [
        {
            "zone_id": "z_north_in",
            "zone_type": "entry",
            "approach": "north",
            "vertices": [[200.0, 50.0], [400.0, 50.0], [400.0, 150.0], [200.0, 150.0]],
        },
        {
            "zone_id": "z_south_out",
            "zone_type": "exit",
            "approach": "south",
            "vertices": [[200.0, 450.0], [400.0, 450.0], [400.0, 550.0], [200.0, 550.0]],
        },
        {
            "zone_id": "z_east_out",
            "zone_type": "exit",
            "approach": "east",
            "vertices": [[500.0, 250.0], [600.0, 250.0], [600.0, 350.0], [500.0, 350.0]],
        },
        {
            "zone_id": "z_north_out",
            "zone_type": "exit",
            "approach": "north",
            "vertices": [[50.0, 50.0], [150.0, 50.0], [150.0, 150.0], [50.0, 150.0]],
        },
    ]

    movement_mapping = {
        "north": {
            "south": "through",
            "east": "left",
            "west": "right",
            "north": "u_turn",
        }
    }

    # 1. North entry -> South exit => through
    traj_through = _create_software_fixture_trajectory(
        track_id=1,
        points_data=[
            (0, 0.0, 300.0, 100.0),  # in z_north_in
            (10, 1.0, 300.0, 300.0),
            (20, 2.0, 300.0, 500.0),  # in z_south_out
        ],
    )
    mov, entry_app, exit_app = derive_movement(traj_through, zones, movement_mapping)
    assert mov == "through"
    assert entry_app == "north"
    assert exit_app == "south"

    # 2. North entry -> East exit => left
    traj_left = _create_software_fixture_trajectory(
        track_id=2,
        points_data=[
            (0, 0.0, 300.0, 100.0),  # in z_north_in
            (10, 1.0, 300.0, 300.0),
            (20, 2.0, 550.0, 300.0),  # in z_east_out
        ],
    )
    mov, entry_app, exit_app = derive_movement(traj_left, zones, movement_mapping)
    assert mov == "left"

    # 3. North entry -> North exit => u_turn
    traj_uturn = _create_software_fixture_trajectory(
        track_id=3,
        points_data=[
            (0, 0.0, 300.0, 100.0),  # in z_north_in
            (10, 1.0, 300.0, 300.0),
            (20, 2.0, 100.0, 100.0),  # in z_north_out
        ],
    )
    mov, entry_app, exit_app = derive_movement(traj_uturn, zones, movement_mapping)
    assert mov == "u_turn"

    # 4. Incomplete track (only entry, never reached exit) => unknown (never guessed)
    traj_no_exit = _create_software_fixture_trajectory(
        track_id=4,
        points_data=[
            (0, 0.0, 300.0, 100.0),  # in z_north_in
            (10, 1.0, 300.0, 300.0),
        ],
    )
    mov, entry_app, exit_app = derive_movement(traj_no_exit, zones, movement_mapping)
    assert mov == "unknown"
    assert entry_app == "north"
    assert exit_app is None

    # 5. Track that never touched an entry zone => unknown
    traj_no_entry = _create_software_fixture_trajectory(
        track_id=5,
        points_data=[
            (0, 0.0, 300.0, 300.0),
            (10, 1.0, 300.0, 500.0),  # in z_south_out
        ],
    )
    mov, entry_app, exit_app = derive_movement(traj_no_entry, zones, movement_mapping)
    assert mov == "unknown"
    assert entry_app is None


def test_tp6_05_15_minute_bin_boundaries() -> None:
    """TP6-05: 15-minute volume bin boundaries are aligned to video timestamps (bin_start_s = k * 900)."""
    crossings = [
        {
            "crossing_event_id": "c1",
            "line_id": "line_1",
            "timestamp_s": 45.0,  # Bin 0: [0, 900)
            "vehicle_class": "car",
            "approach": "north",
            "movement": "through",
            "deduplicated": 0,
        },
        {
            "crossing_event_id": "c2",
            "line_id": "line_1",
            "timestamp_s": 899.9,  # Bin 0: [0, 900)
            "vehicle_class": "car",
            "approach": "north",
            "movement": "through",
            "deduplicated": 0,
        },
        {
            "crossing_event_id": "c3",
            "line_id": "line_1",
            "timestamp_s": 900.0,  # Bin 1: [900, 1800)
            "vehicle_class": "car",
            "approach": "north",
            "movement": "through",
            "deduplicated": 0,
        },
        {
            "crossing_event_id": "c4",
            "line_id": "line_1",
            "timestamp_s": 1850.0,  # Bin 2: [1800, 2700)
            "vehicle_class": "car",
            "approach": "north",
            "movement": "through",
            "deduplicated": 0,
        },
    ]

    bins = aggregate_volume_bins(
        crossings=crossings,
        run_id="run-test",
        video_id="vid-test",
        bin_duration_s=900.0,
        video_duration_s=2700.0,
    )

    assert len(bins) == 3
    bin_starts = [b["bin_start_s"] for b in bins]
    assert bin_starts == [0.0, 900.0, 1800.0]
    assert bins[0]["count"] == 2
    assert bins[1]["count"] == 1
    assert bins[2]["count"] == 1


def test_tp6_06_partial_final_bin_keeps_observed_duration() -> None:
    """TP6-06: Partial final bin keeps observed_duration_s reflecting truncated observation period."""
    crossings = [
        {
            "crossing_event_id": "c1",
            "line_id": "line_1",
            "timestamp_s": 950.0,  # In bin starting at 900.0
            "vehicle_class": "car",
            "approach": "north",
            "movement": "through",
            "deduplicated": 0,
        }
    ]

    # Video duration is 1200 seconds total (bin 0 is 0-900, bin 1 is 900-1200 => 300s observed)
    bins = aggregate_volume_bins(
        crossings=crossings,
        run_id="run-test",
        video_id="vid-test",
        bin_duration_s=900.0,
        video_duration_s=1200.0,
    )

    assert len(bins) == 1
    b = bins[0]
    assert b["bin_start_s"] == 900.0
    assert b["bin_duration_s"] == 900.0
    assert b["observed_duration_s"] == 300.0  # Truncated 1200 - 900 = 300s
    assert b["count"] == 1


def test_tp6_07_hourly_extrapolation_calculation() -> None:
    """TP6-07: Hourly extrapolation is computed as count * 3600 / observed_duration_s."""
    crossings = [
        {
            "crossing_event_id": f"c_{i}",
            "line_id": "line_1",
            "timestamp_s": 920.0 + i,
            "vehicle_class": "bus",
            "approach": "south",
            "movement": "through",
            "deduplicated": 0,
        }
        for i in range(10)  # 10 buses
    ]

    # Observed duration is 300 seconds (5 minutes)
    bins = aggregate_volume_bins(
        crossings=crossings,
        run_id="run-test",
        video_id="vid-test",
        bin_duration_s=900.0,
        video_duration_s=1200.0,
    )

    assert len(bins) == 1
    b = bins[0]
    assert b["count"] == 10
    assert b["observed_duration_s"] == 300.0
    # Expected extrapolation = 10 * 3600 / 300 = 120 vehicles/hour
    assert b["extrapolated_vehicles_per_hour"] == 120.0


def test_tp6_08_zero_duration_bin_extrapolates_to_null() -> None:
    """TP6-08: When observed_duration_s is 0, extrapolated_vehicles_per_hour is None (NULL)."""
    crossings = [
        {
            "crossing_event_id": "c1",
            "line_id": "line_1",
            "timestamp_s": 900.0,
            "vehicle_class": "auto_rickshaw",
            "approach": "west",
            "movement": "left",
            "deduplicated": 0,
        }
    ]

    # Video duration ends exactly at bin boundary 900.0
    bins = aggregate_volume_bins(
        crossings=crossings,
        run_id="run-test",
        video_id="vid-test",
        bin_duration_s=900.0,
        video_duration_s=900.0,
    )

    assert len(bins) == 1
    b = bins[0]
    assert b["observed_duration_s"] == 0.0
    assert b["extrapolated_vehicles_per_hour"] is None


def test_tp6_09_raw_events_preserved_nothing_silently_dropped() -> None:
    """TP6-09: Raw crossing events are preserved in full; deduplicated flag recorded."""
    line = {
        "line_id": "line_1",
        "approach": "north",
        "bidirectional": False,
        "config_version": "cfgver123",
        "geometry_json": {
            "endpoints": [[100.0, 200.0], [500.0, 200.0]],
            "direction_vector": [0.0, 1.0],
        },
    }

    traj = _create_software_fixture_trajectory(
        track_id=99,
        points_data=[
            (0, 0.0, 300.0, 150.0),
            (1, 0.5, 300.0, 250.0),  # Crossing 1 (dedup=0)
            (2, 0.8, 300.0, 150.0),  # Crossing 2 (wrong-way, dedup=1)
            (3, 1.1, 300.0, 250.0),  # Crossing 3 (reentry within 2.0s, dedup=1)
        ],
    )

    crossings = detect_crossings_for_trajectory(traj, [line], min_reentry_gap_s=2.0)
    assert len(crossings) == 3

    # Check that required canonical fields are present in every crossing event
    for c in crossings:
        assert "crossing_event_id" in c
        assert "run_id" in c
        assert "video_id" in c
        assert "line_id" in c
        assert "track_id" in c
        assert "frame_number" in c
        assert "timestamp_s" in c
        assert "vehicle_class" in c
        assert "direction" in c
        assert "approach" in c
        assert "movement" in c
        assert "line_config_version" in c
        assert "deduplicated" in c
        assert c["deduplicated"] in (0, 1)


def test_tp6_gap_rule_prevents_interpolation_through_large_gaps() -> None:
    """Verify that temporal gaps larger than Phase 04 max_gap_seconds do not interpolate crossings."""
    line = {
        "line_id": "line_1",
        "approach": "north",
        "bidirectional": True,
        "config_version": "cfgver123",
        "geometry_json": {
            "endpoints": [[100.0, 200.0], [500.0, 200.0]],
            "direction_vector": None,
        },
    }

    # Time gap between points is 5.0 seconds > max_gap_seconds (1.0s)
    traj_large_gap = _create_software_fixture_trajectory(
        track_id=88,
        points_data=[
            (0, 0.0, 300.0, 150.0),
            (150, 5.0, 300.0, 250.0),  # Gap is 5.0s > 1.0s
        ],
    )

    crossings = detect_crossings_for_trajectory(traj_large_gap, [line], max_gap_seconds=1.0)
    assert len(crossings) == 0  # Not interpolated through large gap


def test_tp6_12_counting_comparison_and_no_acceptance_claim() -> None:
    """TP6-12: Counting comparison reports error metrics with error_tolerance_pct and does NOT state passed/accepted."""
    counted_events = [
        {
            "timestamp_s": 50.0,
            "approach": "north",
            "movement": "through",
            "vehicle_class": "car",
            "deduplicated": 0,
        },
        {
            "timestamp_s": 60.0,
            "approach": "north",
            "movement": "through",
            "vehicle_class": "car",
            "deduplicated": 0,
        },
        {
            "timestamp_s": 70.0,
            "approach": "north",
            "movement": "through",
            "vehicle_class": "car",
            "deduplicated": 1,  # Duplicate; excluded
        },
    ]

    ground_truth_counts = [
        {
            "ground_truth_count_id": "gtc_01",
            "video_segment_id": "seg_01",
            "approach": "north",
            "movement": "through",
            "vehicle_class": "car",
            "observed_count": 2,  # Perfectly matches counted 2
        }
    ]

    video_segments = [
        {
            "segment_id": "seg_01",
            "start_s": 0.0,
            "end_s": 100.0,
        }
    ]

    report = calculate_counting_comparison(
        counted_events=counted_events,
        ground_truth_counts=ground_truth_counts,
        video_segments=video_segments,
        error_tolerance_pct=10.0,
    )

    assert report["total_counted"] == 2
    assert report["total_observed"] == 2
    assert report["total_absolute_error"] == 0
    assert report["total_percent_error"] == 0.0
    assert report["error_tolerance_pct"] == 10.0

    # Invariant check: report MUST NOT declare acceptance or passing
    assert "status" not in report
    assert "passed" not in report
    assert "accepted" not in report
