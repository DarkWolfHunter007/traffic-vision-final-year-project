"""Tests for Phase 06 counting service, database persistence, schema migration, and CLI.

Software fixture notice: Test fixtures are synthetic software fixtures for validating
invariants and error handling; they do not represent real-world CCTV footage validation.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any
import uuid

import pytest
import yaml

from backend.cli import main
from backend.database.connection import (
    SchemaMigrationRequired,
    bootstrap_database,
    connect,
    database_connection,
    migrate_database,
    schema_version,
)
from backend.database.repository import (
    fetch_crossing_events_for_run,
    fetch_ground_truth_counts_for_set,
    fetch_traffic_volume_bins_for_run,
    fetch_video_segments_for_video,
    insert_counting_line,
    insert_run,
    insert_tracks,
    insert_video,
    insert_zone,
)
from backend.services.counting import (
    compare_counts,
    load_ground_truth,
    run_counting,
)


@pytest.fixture
def test_db_setup(tmp_path: Path) -> tuple[Path, str, dict[str, Any]]:
    """Create a bootstrapped database with a registered synthetic video."""
    db_path = tmp_path / "counting_test.sqlite3"
    bootstrap_database(db_path)

    video_id = "vid_synthetic_pattom_01"
    with database_connection(db_path) as conn:
        insert_video(
            conn,
            {
                "video_id": video_id,
                "filename": "synthetic_pattom.mp4",
                "path": str(tmp_path / "synthetic_pattom.mp4"),
                "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                "fps_nominal": 30.0,
                "width": 640,
                "height": 480,
                "duration_s": 120.0,
                "frame_count": 3600,
                "variable_frame_rate": 0,
                "wall_clock_start": "2026-10-14T08:00:00Z",
                "ingested_at": "2026-10-14T08:05:00Z",
                "metadata_json": "{}",
            },
        )

    app_config: dict[str, Any] = {
        "paths": {"database_path": str(db_path)},
        "counting": {
            "bin_duration_s": 900.0,
            "min_reentry_gap_s": 2.0,
            "error_tolerance_pct": 10.0,
            "movement_mapping": {
                "north": {
                    "south": "through",
                    "east": "left",
                    "west": "right",
                    "north": "u_turn",
                }
            },
        },
        "trajectories": {
            "ground_point_method": "bottom_center",
            "max_gap_seconds": 1.0,
            "min_track_length_frames": 2,
            "boundary_margin_px": 20,
        },
    }

    return db_path, video_id, app_config


def test_tp6_10_foreign_key_integrity(test_db_setup: tuple[Path, str, dict[str, Any]]) -> None:
    """TP6-10: Foreign key integrity strictly enforced for video_segments, ground_truth_counts, crossing_events."""
    db_path, video_id, _ = test_db_setup

    with connect(db_path) as conn:
        # 1. video_segments referencing non-existent video_id must fail
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO video_segments (
                    segment_id, video_id, start_s, end_s, start_frame, end_frame
                ) VALUES ('seg_orphan', 'non_existent_video', 0.0, 10.0, 0, 300)
                """
            )

        # 2. ground_truth_counts referencing non-existent video_segment_id must fail
        conn.execute(
            """
            INSERT INTO ground_truth_sets (
                ground_truth_set_id, name, source_description, split_group, created_at
            ) VALUES ('gt_set_1', 'Test Set', 'Software fixture', 'test', '2026-10-14T00:00:00Z')
            """
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO ground_truth_counts (
                    ground_truth_count_id, ground_truth_set_id, video_segment_id,
                    approach, movement, vehicle_class, observed_count
                ) VALUES ('gtc_orphan', 'gt_set_1', 'non_existent_segment', 'north', 'through', 'car', 5)
                """
            )

        # 3. crossing_events referencing non-existent line_id must fail
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO crossing_events (
                    crossing_event_id, run_id, video_id, line_id, track_id,
                    frame_number, timestamp_s, line_config_version
                ) VALUES ('ce_orphan', 'run_orphan', 'vid_orphan', 'non_existent_line', 1, 0, 0.0, 'cfg')
                """
            )


def test_tp6_11_schema_upgrade_from_phase_05_db(tmp_path: Path) -> None:
    """TP6-11: Schema upgrade successfully migrates an existing Phase 05 database to Phase 06 schema."""
    legacy_db = tmp_path / "legacy_phase05.sqlite3"

    # Simulate an existing Phase 05 SQLite database
    with connect(legacy_db) as conn:
        conn.execute("CREATE TABLE schema_migrations (schema_version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
        conn.execute("INSERT INTO schema_migrations VALUES ('phase_05_legacy_hash_abc123', '2026-10-14T00:00:00Z')")
        conn.execute(
            """
            CREATE TABLE videos (
                video_id TEXT PRIMARY KEY, filename TEXT NOT NULL, path TEXT NOT NULL,
                sha256 TEXT NOT NULL, fps_nominal REAL, width INTEGER, height INTEGER,
                duration_s REAL, frame_count INTEGER, variable_frame_rate INTEGER DEFAULT 0,
                wall_clock_start TEXT, ingested_at TEXT NOT NULL, metadata_json TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE processing_runs (
                run_id TEXT PRIMARY KEY, parent_run_id TEXT, video_id TEXT NOT NULL,
                model_version TEXT, config_hash TEXT NOT NULL, config_json TEXT NOT NULL,
                schema_version TEXT NOT NULL, code_version TEXT NOT NULL, source_video_sha256 TEXT NOT NULL,
                started_at TEXT NOT NULL, completed_at TEXT, status TEXT NOT NULL, notes TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE counting_lines (
                line_id TEXT PRIMARY KEY, video_id TEXT NOT NULL, name TEXT NOT NULL,
                approach TEXT, geometry_json TEXT NOT NULL, bidirectional INTEGER DEFAULT 0,
                config_version TEXT NOT NULL, geometry_sha256 TEXT NOT NULL
            )
            """
        )
        # Phase 05 crossing_events WITHOUT deduplicated column
        conn.execute(
            """
            CREATE TABLE crossing_events (
                crossing_event_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, video_id TEXT NOT NULL,
                line_id TEXT NOT NULL, track_id INTEGER NOT NULL, frame_number INTEGER NOT NULL,
                timestamp_s REAL NOT NULL, vehicle_class TEXT, direction TEXT,
                approach TEXT, movement TEXT, line_config_version TEXT NOT NULL
            )
            """
        )
        # Phase 05 traffic_volume_bins WITHOUT observed_duration_s column
        conn.execute(
            """
            CREATE TABLE traffic_volume_bins (
                bin_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, video_id TEXT NOT NULL,
                line_id TEXT NOT NULL, bin_start_s REAL NOT NULL, bin_duration_s REAL NOT NULL DEFAULT 900,
                vehicle_class TEXT, approach TEXT, movement TEXT, count INTEGER NOT NULL,
                extrapolated_vehicles_per_hour REAL
            )
            """
        )
        conn.commit()

    # Prior to explicit migration, bootstrap_database should reject it
    with pytest.raises(SchemaMigrationRequired):
        bootstrap_database(legacy_db)

    # Perform explicit schema migration
    migrated_version = migrate_database(legacy_db)
    assert migrated_version == schema_version()

    # Verify that new columns and tables are present
    with connect(legacy_db) as conn:
        crossing_cols = {row[1] for row in conn.execute("PRAGMA table_info(crossing_events)")}
        assert "deduplicated" in crossing_cols

        bin_cols = {row[1] for row in conn.execute("PRAGMA table_info(traffic_volume_bins)")}
        assert "observed_duration_s" in bin_cols

        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "video_segments" in tables

    # Subsequent bootstrap_database succeeds idempotently
    assert bootstrap_database(legacy_db) == migrated_version


def test_counting_service_end_to_end(
    tmp_path: Path, test_db_setup: tuple[Path, str, dict[str, Any]]
) -> None:
    """Test full counting pipeline execution from tracking run to crossing events and volume bins."""
    db_path, video_id, app_config = test_db_setup

    tracking_run_id = f"run_track_{uuid.uuid4().hex[:8]}"

    with database_connection(db_path) as conn:
        # Register completed parent tracking run
        insert_run(
            conn,
            {
                "run_id": tracking_run_id,
                "parent_run_id": None,
                "video_id": video_id,
                "model_version": None,
                "config_hash": "dummy_config_hash",
                "config_json": "{}",
                "schema_version": schema_version(),
                "code_version": "dummy_git_commit_hash",
                "source_video_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                "started_at": "2026-10-14T08:10:00Z",
                "completed_at": "2026-10-14T08:11:00Z",
                "status": "completed",
                "notes": "Parent tracking test run",
            },
        )

        # Configure counting line
        insert_counting_line(
            conn,
            {
                "line_id": "line_north_entry",
                "video_id": video_id,
                "name": "North Entry Line",
                "approach": "north",
                "geometry_json": json.dumps(
                    {
                        "endpoints": [[100.0, 200.0], [500.0, 200.0]],
                        "direction_vector": [0.0, 1.0],
                    }
                ),
                "bidirectional": 0,
                "config_version": "cfg_ver_north",
                "geometry_sha256": "hash_north_line",
            },
        )

        # Configure entry zone and exit zone
        insert_zone(
            conn,
            {
                "zone_id": "zone_north_in",
                "video_id": video_id,
                "name": "North Entry Zone",
                "zone_type": "entry",
                "approach": "north",
                "geometry_json": json.dumps(
                    {"vertices": [[150.0, 50.0], [450.0, 50.0], [450.0, 180.0], [150.0, 180.0]]}
                ),
                "config_version": "cfg_ver_zin",
                "geometry_sha256": "hash_zone_in",
            },
        )
        insert_zone(
            conn,
            {
                "zone_id": "zone_south_out",
                "video_id": video_id,
                "name": "South Exit Zone",
                "zone_type": "exit",
                "approach": "south",
                "geometry_json": json.dumps(
                    {"vertices": [[150.0, 250.0], [450.0, 250.0], [450.0, 450.0], [150.0, 450.0]]}
                ),
                "config_version": "cfg_ver_zout",
                "geometry_sha256": "hash_zone_out",
            },
        )

        # Track 1: Car moving North -> South across line y=200
        # Track 2: Bus moving North -> South across line y=200
        tracks_data = [
            # Track 1 (Car)
            {
                "track_observation_id": "obs_1_1",
                "run_id": tracking_run_id,
                "video_id": video_id,
                "track_id": 1,
                "frame_number": 0,
                "timestamp_s": 0.0,
                "vehicle_class": "car",
                "confidence": 0.9,
                "x1": 280.0,
                "y1": 80.0,
                "x2": 320.0,
                "y2": 120.0,
                "ground_x": 300.0,
                "ground_y": 120.0,
                "world_x": None,
                "world_y": None,
                "calibration_id": None,
                "trajectory_status": "complete",
            },
            {
                "track_observation_id": "obs_1_2",
                "run_id": tracking_run_id,
                "video_id": video_id,
                "track_id": 1,
                "frame_number": 15,
                "timestamp_s": 0.5,
                "vehicle_class": "car",
                "confidence": 0.92,
                "x1": 280.0,
                "y1": 260.0,
                "x2": 320.0,
                "y2": 300.0,
                "ground_x": 300.0,
                "ground_y": 300.0,
                "world_x": None,
                "world_y": None,
                "calibration_id": None,
                "trajectory_status": "complete",
            },
            # Track 2 (Bus)
            {
                "track_observation_id": "obs_2_1",
                "run_id": tracking_run_id,
                "video_id": video_id,
                "track_id": 2,
                "frame_number": 30,
                "timestamp_s": 1.0,
                "vehicle_class": "bus",
                "confidence": 0.88,
                "x1": 270.0,
                "y1": 90.0,
                "x2": 330.0,
                "y2": 150.0,
                "ground_x": 300.0,
                "ground_y": 150.0,
                "world_x": None,
                "world_y": None,
                "calibration_id": None,
                "trajectory_status": "complete",
            },
            {
                "track_observation_id": "obs_2_2",
                "run_id": tracking_run_id,
                "video_id": video_id,
                "track_id": 2,
                "frame_number": 45,
                "timestamp_s": 1.5,
                "vehicle_class": "bus",
                "confidence": 0.91,
                "x1": 270.0,
                "y1": 240.0,
                "x2": 330.0,
                "y2": 300.0,
                "ground_x": 300.0,
                "ground_y": 300.0,
                "world_x": None,
                "world_y": None,
                "calibration_id": None,
                "trajectory_status": "complete",
            },
        ]
        insert_tracks(conn, tracks_data)

    # Execute counting service
    count_run_id = run_counting(
        parent_run_id=tracking_run_id,
        config=app_config,
        repository_root=tmp_path,
    )
    assert count_run_id is not None

    with database_connection(db_path) as conn:
        crossings = fetch_crossing_events_for_run(conn, count_run_id)
        assert len(crossings) == 2

        # Verify movement derivation for both tracks
        classes = {c["vehicle_class"]: c["movement"] for c in crossings}
        assert classes["car"] == "through"
        assert classes["bus"] == "through"

        # Verify volume bins
        bins = fetch_traffic_volume_bins_for_run(conn, count_run_id)
        assert len(bins) == 2  # 1 for car, 1 for bus
        for b in bins:
            assert b["count"] == 1
            assert b["movement"] == "through"
            assert b["observed_duration_s"] == 120.0  # Video duration was 120s
            assert b["extrapolated_vehicles_per_hour"] == round(1 * 3600 / 120.0, 2)  # 30.0 vph


def test_load_ground_truth_and_compare_counts(
    tmp_path: Path, test_db_setup: tuple[Path, str, dict[str, Any]]
) -> None:
    """Test loading ground-truth YAML software fixture and executing compare-counts."""
    db_path, video_id, app_config = test_db_setup

    # 1. Create a software test fixture YAML file
    gt_file = tmp_path / "ground_truth_fixture.yaml"
    gt_fixture_data = {
        "set": {
            "ground_truth_set_id": "gt_fixture_01",
            "name": "Pattom Synthetic Clip 01 GT",
            "source_description": "Software test fixture for vehicle counting validation",
            "split_group": "test",
        },
        "segments": [
            {
                "segment_id": "seg_clip_01",
                "video_id": video_id,
                "start_s": 0.0,
                "end_s": 60.0,
                "start_frame": 0,
                "end_frame": 1800,
                "label": "interval_01",
                "condition_notes": "Software fixture test interval",
            }
        ],
        "counts": [
            {
                "ground_truth_count_id": "gtc_01",
                "video_segment_id": "seg_clip_01",
                "approach": "north",
                "movement": "through",
                "vehicle_class": "car",
                "observed_count": 5,
            },
            {
                "ground_truth_count_id": "gtc_02",
                "video_segment_id": "seg_clip_01",
                "approach": "north",
                "movement": "through",
                "vehicle_class": "bus",
                "observed_count": 2,
            },
        ],
    }
    with open(gt_file, "w", encoding="utf-8") as f:
        yaml.dump(gt_fixture_data, f)

    load_res = load_ground_truth(gt_file, config=app_config, repository_root=tmp_path)
    assert load_res["status"] == "loaded"
    assert load_res["ground_truth_set_id"] == "gt_fixture_01"
    assert load_res["segments_count"] == 1
    assert load_res["counts_count"] == 2

    # Verify persisted rows
    with database_connection(db_path) as conn:
        segs = fetch_video_segments_for_video(conn, video_id)
        assert len(segs) == 1
        assert segs[0]["segment_id"] == "seg_clip_01"

        counts = fetch_ground_truth_counts_for_set(conn, "gt_fixture_01")
        assert len(counts) == 2

    # 2. Simulate counting run with 4 cars and 2 buses
    count_run_id = f"run_count_{uuid.uuid4().hex[:8]}"
    with database_connection(db_path) as conn:
        insert_run(
            conn,
            {
                "run_id": count_run_id,
                "parent_run_id": None,
                "video_id": video_id,
                "model_version": None,
                "config_hash": "cfg_hash",
                "config_json": "{}",
                "schema_version": schema_version(),
                "code_version": "git_hash",
                "source_video_sha256": "sha",
                "started_at": "2026-10-14T08:00:00Z",
                "completed_at": "2026-10-14T08:01:00Z",
                "status": "completed",
                "notes": "Counting test run",
            },
        )

        insert_counting_line(
            conn,
            {
                "line_id": "line_north_entry",
                "video_id": video_id,
                "name": "North Entry Line",
                "approach": "north",
                "geometry_json": json.dumps(
                    {
                        "endpoints": [[100.0, 200.0], [500.0, 200.0]],
                        "direction_vector": [0.0, 1.0],
                    }
                ),
                "bidirectional": 0,
                "config_version": "cfg_v1",
                "geometry_sha256": "sha_v1",
            },
        )

        simulated_crossings = []
        # 4 cars
        for i in range(4):
            simulated_crossings.append(
                (
                    f"c_car_{i}",
                    count_run_id,
                    video_id,
                    "line_north_entry",
                    i + 1,
                    i * 10,
                    10.0 + i,
                    "car",
                    "forward",
                    "north",
                    "through",
                    "cfg_v1",
                    0,
                )
            )
        # 2 buses
        for i in range(2):
            simulated_crossings.append(
                (
                    f"c_bus_{i}",
                    count_run_id,
                    video_id,
                    "line_north_entry",
                    i + 10,
                    i * 10,
                    20.0 + i,
                    "bus",
                    "forward",
                    "north",
                    "through",
                    "cfg_v1",
                    0,
                )
            )

        conn.executemany(
            """
            INSERT INTO crossing_events (
                crossing_event_id, run_id, video_id, line_id, track_id, frame_number,
                timestamp_s, vehicle_class, direction, approach, movement,
                line_config_version, deduplicated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            simulated_crossings,
        )

    # 3. Compare counts
    report = compare_counts(
        run_id=count_run_id,
        ground_truth_set_id="gt_fixture_01",
        config=app_config,
        repository_root=tmp_path,
    )

    assert report["run_id"] == count_run_id
    assert report["ground_truth_set_id"] == "gt_fixture_01"
    assert report["total_counted"] == 6  # 4 cars + 2 buses
    assert report["total_observed"] == 7  # 5 cars + 2 buses
    assert report["total_absolute_error"] == 1
    assert report["total_percent_error"] == round(1 / 7 * 100.0, 2)
    assert report["error_tolerance_pct"] == 10.0

    # Invariant: report MUST NOT declare acceptance
    assert "status" not in report
    assert "passed" not in report
    assert "accepted" not in report


def test_cli_counting_commands(
    tmp_path: Path,
    test_db_setup: tuple[Path, str, dict[str, Any]],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test CLI commands: migrate-db, load-ground-truth, and compare-counts."""
    db_path, video_id, app_config = test_db_setup

    cfg_file = tmp_path / "cli_config.yaml"
    with open(cfg_file, "w", encoding="utf-8") as f:
        yaml.dump(app_config, f)

    gt_file = tmp_path / "cli_gt.yaml"
    with open(gt_file, "w", encoding="utf-8") as f:
        yaml.dump(
            {
                "set": {
                    "ground_truth_set_id": "gt_cli_set",
                    "name": "CLI GT Set",
                    "source_description": "Software test fixture",
                    "split_group": "test",
                },
                "segments": [
                    {
                        "segment_id": "seg_cli_01",
                        "video_id": video_id,
                        "start_s": 0.0,
                        "end_s": 100.0,
                        "start_frame": 0,
                        "end_frame": 3000,
                    }
                ],
                "counts": [
                    {
                        "ground_truth_count_id": "gtc_cli_01",
                        "video_segment_id": "seg_cli_01",
                        "approach": "north",
                        "movement": "through",
                        "vehicle_class": "car",
                        "observed_count": 10,
                    }
                ],
            },
            f,
        )

    # 1. Test migrate-db CLI
    monkeypatch.setattr(
        "sys.argv",
        ["traffic-vision", "migrate-db", "--config", str(cfg_file)],
    )
    main()
    out_migrate = capsys.readouterr().out
    data_migrate = json.loads(out_migrate)
    assert "schema_version" in data_migrate

    # 2. Test load-ground-truth CLI
    monkeypatch.setattr(
        "sys.argv",
        ["traffic-vision", "load-ground-truth", str(gt_file), "--config", str(cfg_file)],
    )
    main()
    out_gt = capsys.readouterr().out
    data_gt = json.loads(out_gt)
    assert data_gt["status"] == "loaded"
    assert data_gt["ground_truth_set_id"] == "gt_cli_set"

    # 3. Setup a parent tracking run and counting line to test 'count' CLI
    tracking_run_id = f"cli_track_{uuid.uuid4().hex[:8]}"
    with database_connection(db_path) as conn:
        insert_run(
            conn,
            {
                "run_id": tracking_run_id,
                "parent_run_id": None,
                "video_id": video_id,
                "model_version": None,
                "config_hash": "cfg_hash",
                "config_json": "{}",
                "schema_version": schema_version(),
                "code_version": "git_hash",
                "source_video_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                "started_at": "2026-10-14T08:00:00Z",
                "completed_at": "2026-10-14T08:01:00Z",
                "status": "completed",
                "notes": "Parent tracking test run",
            },
        )
        insert_counting_line(
            conn,
            {
                "line_id": "line_cli",
                "video_id": video_id,
                "name": "CLI Line",
                "approach": "north",
                "geometry_json": json.dumps(
                    {
                        "endpoints": [[100.0, 200.0], [500.0, 200.0]],
                        "direction_vector": [0.0, 1.0],
                    }
                ),
                "bidirectional": 0,
                "config_version": "cfg_cli",
                "geometry_sha256": "sha_cli",
            },
        )

    monkeypatch.setattr(
        "sys.argv",
        ["traffic-vision", "count", tracking_run_id, "--config", str(cfg_file)],
    )
    main()
    out_count = capsys.readouterr().out
    data_count = json.loads(out_count)
    assert "run_id" in data_count
    assert data_count["parent_run_id"] == tracking_run_id
    count_run_id = data_count["run_id"]

    # 4. Test compare-counts CLI
    monkeypatch.setattr(
        "sys.argv",
        ["traffic-vision", "compare-counts", count_run_id, "--ground-truth-set", "gt_cli_set", "--config", str(cfg_file)],
    )
    main()
    out_cmp = capsys.readouterr().out
    data_cmp = json.loads(out_cmp)
    assert data_cmp["run_id"] == count_run_id
    assert data_cmp["ground_truth_set_id"] == "gt_cli_set"
    assert "error_tolerance_pct" in data_cmp
    assert "passed" not in data_cmp
    assert "accepted" not in data_cmp

