"""Ground-truth comparison lineage, tolerance status and export aggregation tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.database.connection import bootstrap_database, database_connection, schema_version
from backend.database.repository import (
    fetch_run_export_data,
    insert_calibration_run,
    insert_counting_line,
    insert_run,
    insert_video,
)
from backend.services.counting import compare_counts
from backend.services.dashboard import get_dashboard_ground_truth

VID = "vid_lin"
CFG = {"counting": {"error_tolerance_pct": 10.0}}


def _run(conn, run_id, parent=None):
    insert_run(conn, {
        "run_id": run_id, "parent_run_id": parent, "video_id": VID, "model_version": None,
        "config_hash": "h", "config_json": "{}", "schema_version": schema_version(),
        "code_version": "c", "source_video_sha256": "s", "started_at": "2026-10-14T08:00:00Z",
        "completed_at": "2026-10-14T08:01:00Z", "status": "completed", "notes": "n",
    })


@pytest.fixture
def conn(tmp_path: Path):
    db = tmp_path / "t.sqlite3"
    bootstrap_database(db)
    with database_connection(db) as c:
        insert_video(c, {
            "video_id": VID, "filename": "a.mp4", "path": "a.mp4", "sha256": "0" * 64,
            "fps_nominal": 30.0, "width": 64, "height": 48, "duration_s": 60.0,
            "frame_count": 1800, "variable_frame_rate": 0, "wall_clock_start": None,
            "ingested_at": "2026-10-14T08:00:00Z", "metadata_json": "{}",
        })
        insert_counting_line(c, {
            "line_id": "L", "video_id": VID, "name": "L", "approach": "north",
            "geometry_json": "{}", "bidirectional": 0, "config_version": "v", "geometry_sha256": "g",
        })
        _run(c, "root")
        _run(c, "count_run", "root")
        _run(c, "review_run", "root")
        c.execute("INSERT INTO ground_truth_sets (ground_truth_set_id, name, source_description, split_group, created_at) VALUES ('gt','GT','d','test','2026-10-14T08:00:00Z')")
        c.execute("INSERT INTO video_segments (segment_id, video_id, start_s, end_s, start_frame, end_frame, label) VALUES ('seg',?,0,60,0,1800,'l')", (VID,))
        c.execute("INSERT INTO ground_truth_counts (ground_truth_count_id, ground_truth_set_id, video_segment_id, approach, movement, vehicle_class, observed_count) VALUES ('g1','gt','seg','north','through','car',10)")
        yield c


def _cross(c, run_id, n):
    for i in range(n):
        c.execute(
            "INSERT INTO crossing_events (crossing_event_id, run_id, video_id, line_id, track_id, frame_number, timestamp_s, vehicle_class, direction, approach, movement, line_config_version, deduplicated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0)",
            (f"{run_id}_{i}", run_id, VID, "L", i, i, 1.0 + i, "car", "forward", "north", "through", "v"),
        )


def test_review_run_resolves_sibling_counting_crossings(conn) -> None:
    _cross(conn, "count_run", 10)
    rep = compare_counts("review_run", config=CFG, connection=conn)
    assert rep["total_counted"] == 10 and rep["total_percent_error"] == 0.0


def test_no_counting_results_in_lineage_is_unavailable_not_zero(conn) -> None:
    with pytest.raises(ValueError):
        compare_counts("review_run", config=CFG, connection=conn)
    res = get_dashboard_ground_truth("review_run", config=CFG, connection=conn)
    assert res["status"] == "unavailable" and res["report"] is None


def test_ambiguous_lineage_is_unavailable(conn) -> None:
    _cross(conn, "count_run", 10)
    _cross(conn, "root", 10)
    with pytest.raises(ValueError):
        compare_counts("review_run", config=CFG, connection=conn)


def test_ground_truth_status_reflects_tolerance(conn) -> None:
    _cross(conn, "count_run", 10)
    assert get_dashboard_ground_truth("count_run", config=CFG, connection=conn)["status"] == "valid"
    conn.execute("DELETE FROM crossing_events")
    _cross(conn, "count_run", 5)
    res = get_dashboard_ground_truth("count_run", config=CFG, connection=conn)
    assert res["status"] == "out_of_tolerance"
    assert res["report"]["total_percent_error"] == 50.0


def test_export_speed_stats_aggregate_across_lineage(conn) -> None:
    insert_calibration_run(conn, {
        "calibration_id": "cal", "run_id": "root", "video_id": VID, "method": "homography",
        "point_count": 4, "held_out_point_count": 1, "reprojection_error_m_mean": 0.1,
        "reprojection_error_m_max": 0.2, "distortion_checked": 1, "flat_road_assumption": 1,
        "accepted": 1, "parameters_json": "{}",
    })
    for rid, kmh in (("count_run", 10.0), ("review_run", 30.0)):
        conn.execute(
            "INSERT INTO speed_observations (speed_observation_id, run_id, video_id, track_id, timestamp_s, speed_mps, speed_kmh, calibration_id, status, smoothing_window, ground_point_method) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (f"s_{rid}", rid, VID, 1, 1.0, kmh / 3.6, kmh, "cal", "valid", 3, "bottom_center"),
        )
    data = fetch_run_export_data(conn, "count_run")
    assert data["speed_stats"]["total_observations"] == 2
    assert data["speed_stats"]["mean_speed_kmh"] == 20.0
    assert data["speed_stats"]["max_speed_kmh"] == 30.0
