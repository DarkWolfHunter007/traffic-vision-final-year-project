"""Integration tests for Phase 13 export service and CLI commands (TP13-07..TP13-10, TP13-12, TP13-16)."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import pytest

from backend.cli import build_parser, main
from backend.config import ConfigError, load_config
from backend.database.connection import bootstrap_database
from backend.database.repository import (
    insert_crossing_events,
    insert_counting_line,
    insert_manual_review,
    insert_queue_events,
    insert_run,
    insert_speed_observations,
    insert_stop_events,
    insert_tracks,
    insert_traffic_volume_bins,
    insert_video,
    insert_zone,
)
from backend.services.dashboard import get_dashboard_run_summary
from backend.services.export import export_run, get_export_manifest


def _setup_test_db(db_path: Path) -> sqlite3.Connection:
    bootstrap_database(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    # Insert software test fixtures with clear labelling
    insert_video(
        conn,
        {
            "video_id": "vid_fixture_p13",
            "filename": "test_stream.mp4",
            "path": "data/raw/test_stream.mp4",
            "sha256": "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
            "fps_nominal": 25.0,
            "width": 1280,
            "height": 720,
            "duration_s": 30.0,
            "frame_count": 750,
            "variable_frame_rate": 0,
            "wall_clock_start": "2026-10-14T02:00:00Z",
            "ingested_at": "2026-10-14T02:01:00Z",
            "metadata_json": "{}",
        },
    )

    insert_counting_line(
        conn,
        {
            "line_id": "line_north",
            "video_id": "vid_fixture_p13",
            "name": "North Counting Line",
            "approach": "north",
            "geometry_json": '{"x1": 0, "y1": 500, "x2": 1280, "y2": 500}',
            "bidirectional": 0,
            "config_version": "v1.0",
            "geometry_sha256": "line_hash_test",
        },
    )

    insert_zone(
        conn,
        {
            "zone_id": "zone_north",
            "video_id": "vid_fixture_p13",
            "name": "North Queue Zone",
            "zone_type": "queue",
            "approach": "north",
            "geometry_json": "[[0, 0], [100, 0], [100, 100], [0, 100]]",
            "config_version": "v1.0",
            "geometry_sha256": "zone_hash_test",
        },
    )

    insert_run(
        conn,
        {
            "run_id": "run_root_tracking",
            "parent_run_id": None,
            "video_id": "vid_fixture_p13",
            "model_version": None,
            "config_hash": "cfg_hash_test",
            "config_json": "{}",
            "schema_version": "schema_hash_test",
            "code_version": "git_sha_test",
            "source_video_sha256": "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
            "started_at": "2026-10-14T02:02:00Z",
            "status": "completed",
            "notes": "Tracking root run software fixture",
        },
    )

    insert_run(
        conn,
        {
            "run_id": "run_child_counting",
            "parent_run_id": "run_root_tracking",
            "video_id": "vid_fixture_p13",
            "model_version": None,
            "config_hash": "cfg_hash_test",
            "config_json": "{}",
            "schema_version": "schema_hash_test",
            "code_version": "git_sha_test",
            "source_video_sha256": "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
            "started_at": "2026-10-14T02:05:00Z",
            "status": "completed",
            "notes": "Counting child run software fixture",
        },
    )

    # Insert tracks
    insert_tracks(
        conn,
        [
            {
                "track_observation_id": "obs_1",
                "run_id": "run_root_tracking",
                "video_id": "vid_fixture_p13",
                "track_id": 1,
                "frame_number": 10,
                "timestamp_s": 0.4,
                "vehicle_class": "car",
                "confidence": 0.88,
                "x1": 100, "y1": 200, "x2": 150, "y2": 260,
                "ground_x": 125, "ground_y": 260,
                "world_x": None, "world_y": None,
                "calibration_id": None,
                "trajectory_status": "complete",
            },
            {
                "track_observation_id": "obs_2",
                "run_id": "run_root_tracking",
                "video_id": "vid_fixture_p13",
                "track_id": 2,
                "frame_number": 12,
                "timestamp_s": 0.48,
                "vehicle_class": "bus",
                "confidence": 0.92,
                "x1": 300, "y1": 200, "x2": 400, "y2": 320,
                "ground_x": 350, "ground_y": 320,
                "world_x": None, "world_y": None,
                "calibration_id": None,
                "trajectory_status": "complete",
            },
        ],
    )

    # Insert volume bins
    insert_traffic_volume_bins(
        conn,
        [
            {
                "bin_id": "bin_test_01",
                "run_id": "run_child_counting",
                "video_id": "vid_fixture_p13",
                "line_id": "line_north",
                "bin_start_s": 0.0,
                "bin_duration_s": 900.0,
                "observed_duration_s": 30.0,
                "vehicle_class": "car",
                "approach": "north",
                "movement": "through",
                "count": 8,
                "extrapolated_vehicles_per_hour": 960.0,
            },
            {
                "bin_id": "bin_test_02",
                "run_id": "run_child_counting",
                "video_id": "vid_fixture_p13",
                "line_id": "line_north",
                "bin_start_s": 0.0,
                "bin_duration_s": 900.0,
                "observed_duration_s": 30.0,
                "vehicle_class": "bus",
                "approach": "north",
                "movement": "through",
                "count": 2,
                "extrapolated_vehicles_per_hour": 240.0,
            },
        ],
    )

    # Insert speed observations
    conn.execute(
        """
        INSERT INTO calibration_runs (
            calibration_id, run_id, video_id, method, point_count,
            held_out_point_count, reprojection_error_m_mean,
            reprojection_error_m_max, distortion_checked, flat_road_assumption,
            accepted, parameters_json
        ) VALUES (
            'calib_fixture', 'run_root_tracking', 'vid_fixture_p13', 'planar_homography',
            6, 2, 0.42, 0.65, 0, 1, 1, '{\"h\": []}'
        )
        """
    )
    insert_speed_observations(
        conn,
        [
            {
                "speed_observation_id": "spd_obs_1",
                "run_id": "run_root_tracking",
                "video_id": "vid_fixture_p13",
                "track_id": 1,
                "timestamp_s": 0.4,
                "speed_mps": 11.11,
                "speed_kmh": 40.0,
                "calibration_id": "calib_fixture",
                "status": "valid",
                "smoothing_window": 0.5,
                "ground_point_method": "bottom_center",
            },
            {
                "speed_observation_id": "spd_obs_2",
                "run_id": "run_root_tracking",
                "video_id": "vid_fixture_p13",
                "track_id": 2,
                "timestamp_s": 0.48,
                "speed_mps": None,
                "speed_kmh": None,
                "calibration_id": "calib_fixture",
                "status": "unavailable",
                "smoothing_window": 0.5,
                "ground_point_method": "bottom_center",
            },
        ],
    )

    # Insert stop events and queue events
    insert_stop_events(
        conn,
        [
            {
                "stop_event_id": "stop_1",
                "run_id": "run_root_tracking",
                "video_id": "vid_fixture_p13",
                "track_id": 1,
                "start_timestamp_s": 10.0,
                "end_timestamp_s": 16.5,
                "duration_s": 6.5,
                "threshold_kmh": 5.0,
                "status": "valid",
            }
        ],
    )
    insert_queue_events(
        conn,
        [
            {
                "queue_event_id": "q_1",
                "run_id": "run_root_tracking",
                "video_id": "vid_fixture_p13",
                "zone_id": "zone_north",
                "approach": "north",
                "timestamp_s": 12.0,
                "queue_length_m": 15.2,
                "queued_vehicle_count": 3,
                "status": "valid",
            }
        ],
    )

    # Insert manual review
    insert_manual_review(
        conn,
        {
            "review_id": "rev_01",
            "run_id": "run_root_tracking",
            "video_id": "vid_fixture_p13",
            "track_id": 1,
            "detection_id": None,
            "frame_number": 10,
            "timestamp_s": 0.4,
            "original_class": "car",
            "corrected_class": "auto_rickshaw",
            "original_bbox_json": None,
            "corrected_bbox_json": None,
            "reason": "class_ambiguity",
            "review_status": "approved",
            "reviewer": "research_auditor",
            "reviewed_at": "2026-10-14T02:10:00Z",
            "snippet_path": None,
        },
    )

    conn.commit()
    return conn


def test_tp13_07_export_run_multi_format_and_determinism(tmp_path: Path) -> None:
    """TP13-01..TP13-05: Run export produces CSV, JSON, SQLite, and bit-for-bit identical content hash across runs."""
    db_path = tmp_path / "test.sqlite3"
    conn = _setup_test_db(db_path)
    export_dir = tmp_path / "exports"

    res1 = export_run(
        run_id="run_child_counting",
        output_dir=export_dir,
        export_format="all",
        include_raw=True,
        connection=conn,
    )

    assert Path(res1["export_dir"]).is_dir()
    manifest_path = Path(res1["manifest_path"])
    assert manifest_path.is_file()

    # Verify manifest fields
    manifest = get_export_manifest(manifest_path)
    assert manifest["run_id"] == "run_child_counting"
    assert manifest["source_video_sha256"] == "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
    assert manifest["content_hash"] == res1["content_hash"]

    # Verify exported files existence
    assert (Path(res1["export_dir"]) / "traffic_volume_bins.csv").is_file()
    assert (Path(res1["export_dir"]) / "observed_period_summary.csv").is_file()
    assert (Path(res1["export_dir"]) / "run_summary.json").is_file()
    assert (Path(res1["export_dir"]) / "export.sqlite").is_file()

    # Re-run export: content hash must be byte-for-byte identical
    res2 = export_run(
        run_id="run_child_counting",
        output_dir=export_dir,
        export_format="all",
        include_raw=True,
        connection=conn,
    )
    assert res1["content_hash"] == res2["content_hash"]

    conn.close()


def test_tp13_08_sqlite_export_readability(tmp_path: Path) -> None:
    """TP13-03: Exported SQLite database can be independently opened and queried."""
    db_path = tmp_path / "test.sqlite3"
    conn = _setup_test_db(db_path)
    export_dir = tmp_path / "exports"

    res = export_run(
        run_id="run_child_counting",
        output_dir=export_dir,
        export_format="sqlite",
        connection=conn,
    )
    conn.close()

    sqlite_file = Path(res["export_dir"]) / "export.sqlite"
    assert sqlite_file.is_file()

    ext_conn = sqlite3.connect(str(sqlite_file))
    ext_conn.row_factory = sqlite3.Row
    try:
        bins = ext_conn.execute("SELECT * FROM traffic_volume_bins").fetchall()
        assert len(bins) == 2
        assert bins[0]["vehicle_class"] in {"car", "bus"}

        runs = ext_conn.execute("SELECT * FROM processing_runs").fetchall()
        assert len(runs) == 1
        assert runs[0]["run_id"] == "run_child_counting"
    finally:
        ext_conn.close()


def test_tp13_09_tracking_and_review_quality_computation(tmp_path: Path) -> None:
    """TP13-09, TP13-10: Tracking quality metrics and review status correctly computed across child/parent runs."""
    db_path = tmp_path / "test.sqlite3"
    conn = _setup_test_db(db_path)

    summary = get_dashboard_run_summary("run_child_counting", connection=conn)

    tq = summary["tracking_quality"]
    assert tq["total_tracks"] == 2
    assert tq["total_observations"] == 2
    assert tq["trajectory_status_counts"]["complete"] == 2
    assert tq["trajectory_status_counts"]["invalid"] == 0

    rev = summary["review_status"]
    assert rev["total_reviews"] == 1
    assert rev["approved_count"] == 1
    assert rev["class_corrected_count"] == 1

    conn.close()


def test_tp13_10_speed_and_queue_summaries_in_dashboard(tmp_path: Path) -> None:
    """TP13-07, TP13-08: Speed and queue summaries report valid stats and do not fabricate zero for missing values."""
    db_path = tmp_path / "test.sqlite3"
    conn = _setup_test_db(db_path)

    summary = get_dashboard_run_summary("run_child_counting", connection=conn)

    spd = summary["speed_summary"]
    assert spd["total_observations"] == 2
    assert spd["valid_count"] == 1
    assert spd["unavailable_count"] == 1
    assert spd["mean_speed_kmh"] == 40.0

    que = summary["queue_summary"]
    assert que["stops"]["total"] == 1
    assert que["stops"]["valid_stops"] == 1
    assert que["stops"]["mean_duration_s"] == 6.5
    assert que["queues"]["total"] == 1
    assert que["queues"]["formed_queues"] == 1

    conn.close()


def test_tp13_12_cli_export_and_dashboard_commands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """TP13-12: CLI export, show-export-manifest, and dashboard-summary execute and output valid JSON."""
    import sys
    db_path = tmp_path / "test_cli.sqlite3"
    _setup_test_db(db_path)
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        f"""
paths:
  raw_root: data/raw
  processed_root: data/processed
  database_path: "{db_path.as_posix()}"
input:
  supported_formats: [.mp4]
timestamp:
  strategy: decoder_pts
streaming:
  frame_batch_size: 500
resources:
  policy: cpu
logging:
  level: INFO
export:
  output_dir: "{tmp_path.as_posix()}/cli_exports"
  formats: [csv, json, sqlite]
  default_format: all
  include_raw_events: true
dashboard:
  host: "127.0.0.1"
  port: 8000
  summary_interval_s: 900.0
""",
        encoding="utf-8",
    )

    # 1. Test CLI export
    monkeypatch.setattr(sys, "argv", ["traffic-vision", "export", "run_child_counting", "--config", str(cfg_file)])
    main()
    captured = capsys.readouterr()
    res = json.loads(captured.out)
    assert res["run_id"] == "run_child_counting"
    assert "manifest_path" in res

    # 2. Test CLI show-export-manifest
    monkeypatch.setattr(sys, "argv", ["traffic-vision", "show-export-manifest", res["manifest_path"], "--config", str(cfg_file)])
    main()
    captured_m = capsys.readouterr()
    man = json.loads(captured_m.out)
    assert man["run_id"] == "run_child_counting"
    assert "content_hash" in man

    # 3. Test CLI dashboard-summary
    monkeypatch.setattr(sys, "argv", ["traffic-vision", "dashboard-summary", "run_child_counting", "--config", str(cfg_file)])
    main()
    captured_d = capsys.readouterr()
    dash = json.loads(captured_d.out)
    assert dash["run_id"] == "run_child_counting"
    assert "validation_status" in dash


def test_tp13_16_configuration_validation() -> None:
    """TP13-16: Configuration validation enforces valid export formats, port ranges, and required types."""
    cfg = load_config()
    assert "export" in cfg
    assert "dashboard" in cfg
    assert cfg["export"]["default_format"] == "all"
    assert cfg["dashboard"]["port"] == 8000

    # Invalid export format
    with pytest.raises(ConfigError, match="export.formats contains invalid format"):
        load_config(overrides={"export": {"formats": ["invalid_fmt"]}})

    # Invalid port number
    with pytest.raises(ConfigError, match="dashboard.port must be an integer"):
        load_config(overrides={"dashboard": {"port": 99999}})

    # Non-positive summary interval
    with pytest.raises(ConfigError, match="dashboard.summary_interval_s must be a positive number"):
        load_config(overrides={"dashboard": {"summary_interval_s": -10.0}})
