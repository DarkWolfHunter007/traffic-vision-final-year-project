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


def _run(conn, run_id, parent=None, status="completed", video=VID, notes="n", config_json="{}"):
    insert_run(conn, {
        "run_id": run_id, "parent_run_id": parent, "video_id": video, "model_version": None,
        "config_hash": "h", "config_json": config_json, "schema_version": schema_version(),
        "code_version": "c", "source_video_sha256": "s", "started_at": "2026-10-14T08:00:00Z",
        "completed_at": "2026-10-14T08:01:00Z", "status": status, "notes": notes,
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


# ---- hardening: counting-run identity, status, video scoping, tolerance, CLI, escaping ----

COUNTING_CFG = '{"_run_stage": "counting"}'


def test_zero_count_counting_rerun_does_not_borrow_sibling_crossings(conn) -> None:
    _run(conn, "zero_run", "root", notes="Phase 06 vehicle counting run", config_json=COUNTING_CFG)
    _cross(conn, "count_run", 10)
    rep = compare_counts("zero_run", config=CFG, connection=conn)
    assert rep["total_counted"] == 0


def test_failed_selected_run_is_unavailable(conn) -> None:
    _run(conn, "bad", "root", status="failed", notes="Failed: x", config_json=COUNTING_CFG)
    _cross(conn, "count_run", 10)
    with pytest.raises(ValueError):
        compare_counts("bad", config=CFG, connection=conn)
    assert get_dashboard_ground_truth("bad", config=CFG, connection=conn)["status"] == "unavailable"


def test_failed_source_run_is_not_borrowed(conn) -> None:
    conn.execute("UPDATE processing_runs SET status='failed' WHERE run_id='count_run'")
    _cross(conn, "count_run", 10)
    with pytest.raises(ValueError):
        compare_counts("review_run", config=CFG, connection=conn)


def test_cross_video_parent_is_ignored(conn) -> None:
    conn.execute("INSERT INTO videos (video_id, filename, path, sha256, fps_nominal, width, height, duration_s, frame_count, variable_frame_rate, ingested_at, metadata_json) VALUES ('other','b.mp4','b.mp4',?,30,64,48,60,1800,0,'2026-10-14T08:00:00Z','{}')", ("1" * 64,))
    _run(conn, "foreign_root", None, video="other")
    _run(conn, "foreign_review", "foreign_root", video="other")
    _run(conn, "cross_child", "foreign_root", video=VID)
    _cross(conn, "count_run", 10)
    from backend.database.repository import fetch_lineage_run_ids
    assert fetch_lineage_run_ids(conn, "cross_child") == ["cross_child"]
    with pytest.raises(ValueError):
        compare_counts("cross_child", config=CFG, connection=conn)


def test_zero_count_counting_sibling_makes_lineage_ambiguous(conn) -> None:
    _run(conn, "zero_run", "root", notes="Phase 06 vehicle counting run", config_json=COUNTING_CFG)
    _cross(conn, "count_run", 10)
    with pytest.raises(ValueError):
        compare_counts("review_run", config=CFG, connection=conn)


def test_tolerance_headline_uses_total_and_rows_flagged_separately(conn) -> None:
    conn.execute("INSERT INTO ground_truth_counts (ground_truth_count_id, ground_truth_set_id, video_segment_id, approach, movement, vehicle_class, observed_count) VALUES ('g2','gt','seg','north','through','truck',10)")
    _cross(conn, "count_run", 10)  # cars 10/10, trucks 0/10 -> total 10/20 = 50% error
    res = get_dashboard_ground_truth("count_run", config=CFG, connection=conn)
    assert res["status"] == "out_of_tolerance"
    conn.execute("DELETE FROM crossing_events")
    conn.execute("UPDATE ground_truth_counts SET observed_count = 10 WHERE ground_truth_count_id='g1'")
    conn.execute("UPDATE ground_truth_counts SET observed_count = 10 WHERE ground_truth_count_id='g2'")
    # 12 cars, 8 trucks -> total 20/20 exact, rows 20% off
    for i in range(12):
        conn.execute("INSERT INTO crossing_events (crossing_event_id, run_id, video_id, line_id, track_id, frame_number, timestamp_s, vehicle_class, direction, approach, movement, line_config_version, deduplicated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0)", (f"c{i}", "count_run", VID, "L", i, i, 1.0 + i, "car", "forward", "north", "through", "v"))
    for i in range(8):
        conn.execute("INSERT INTO crossing_events (crossing_event_id, run_id, video_id, line_id, track_id, frame_number, timestamp_s, vehicle_class, direction, approach, movement, line_config_version, deduplicated) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0)", (f"t{i}", "count_run", VID, "L", 100 + i, 100 + i, 1.0 + i, "truck", "forward", "north", "through", "v"))
    res = get_dashboard_ground_truth("count_run", config=CFG, connection=conn)
    assert res["status"] == "valid"
    flags = [r["within_tolerance"] for r in res["report"]["comparisons"]]
    assert flags and False in flags


def test_compare_counts_cli_error_path(monkeypatch, capsys) -> None:
    import json
    from backend import cli

    def boom(*a, **k):
        raise ValueError("ambiguous lineage")

    monkeypatch.setattr(cli, "compare_counts", boom)
    monkeypatch.setattr("sys.argv", ["traffic-vision", "compare-counts", "run_x"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    err = json.loads(capsys.readouterr().err)
    assert err["status"] == "unavailable" and "ambiguous" in err["error"]


def test_app_js_escapes_api_data() -> None:
    js = (Path(__file__).resolve().parent.parent / "frontend" / "app.js").read_text(encoding="utf-8")
    for raw in ("${b.approach", "${b.movement", "${b.vehicle_class", "${data.export_dir}",
                "${data.content_hash", "${err.message}"):
        assert raw not in js.replace("escapeHtml(" + raw[2:], "")
    assert "escapeHtml(err.message)" in js
    assert "escapeHtml(data.export_dir)" in js
    assert js.count("escapeHtml(`${") >= 3  # formatters escape inside
