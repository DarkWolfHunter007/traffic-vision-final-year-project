"""Phase 09 integration tests for queue detection service, database persistence, and CLI.

All test fixtures in this module are synthetic software fixtures, explicitly
labelled as such. No real-world research measurements or calibration points
are fabricated.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys
from typing import Any
from uuid import uuid4

import cv2
import numpy as np
import pytest

from backend.calibration import project_world_to_image
from backend.cli import build_parser, main
from backend.config import canonical_json, config_hash, load_config
from backend.database.connection import (
    bootstrap_database,
    database_connection,
    schema_version,
)
from backend.database.repository import (
    fetch_queue_detection_stats,
    fetch_queue_events_for_run,
    fetch_run_by_id,
    fetch_stop_events_for_run,
    insert_calibration_run,
    insert_counting_line,
    insert_run,
    insert_speed_observations,
    insert_tracks,
    insert_video,
    insert_zone,
)
from backend.services.ingestion import _utc_now, current_code_version
from backend.services.queue import (
    get_queue_events,
    get_queue_summary,
    get_stop_events,
    run_queue_detection,
)

# Synthetic software test fixtures
SOFTWARE_FIXTURE_SRC_PTS = np.array(
    [
        [200.0, 500.0],
        [600.0, 500.0],
        [500.0, 200.0],
        [300.0, 200.0],
    ],
    dtype=np.float64,
)
SOFTWARE_FIXTURE_DST_PTS = np.array(
    [
        [0.0, 0.0],
        [10.0, 0.0],
        [10.0, 30.0],
        [0.0, 30.0],
    ],
    dtype=np.float64,
)
_SOFTWARE_H_TRUE, _ = cv2.findHomography(SOFTWARE_FIXTURE_SRC_PTS, SOFTWARE_FIXTURE_DST_PTS)
_SOFTWARE_H_INV = np.linalg.inv(_SOFTWARE_H_TRUE)


@pytest.fixture
def queue_test_env(tmp_path: Path) -> dict[str, Any]:
    """Set up database with synthetic video, calibration, zones, lines, tracking, and speed runs."""
    db_path = tmp_path / "queue_test.sqlite3"
    bootstrap_database(db_path)

    video_id = "vid_synthetic_queue_fixture"
    tracking_run_id = str(uuid4())
    speed_run_id = str(uuid4())
    calib_run_id = str(uuid4())
    accepted_calib_id = str(uuid4())
    rejected_calib_id = str(uuid4())

    config = load_config(overrides={"paths": {"database_path": str(db_path)}})

    with database_connection(db_path) as conn:
        # Ingest video
        insert_video(
            conn,
            {
                "video_id": video_id,
                "filename": "synthetic_pattom.mp4",
                "path": str(tmp_path / "synthetic_pattom.mp4"),
                "sha256": "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
                "fps_nominal": 30.0,
                "width": 1920,
                "height": 1080,
                "duration_s": 10.0,
                "frame_count": 300,
                "variable_frame_rate": 0,
                "wall_clock_start": None,
                "ingested_at": _utc_now(),
                "metadata_json": None,
            },
        )

        # Tracking parent run
        insert_run(
            conn,
            {
                "run_id": tracking_run_id,
                "parent_run_id": None,
                "video_id": video_id,
                "model_version": None,
                "config_hash": config_hash(config),
                "config_json": canonical_json(config),
                "schema_version": schema_version(),
                "code_version": current_code_version(tmp_path),
                "source_video_sha256": "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
                "started_at": _utc_now(),
                "status": "completed",
                "notes": "Synthetic software fixture tracking run",
            },
        )

        # Speed parent run
        insert_run(
            conn,
            {
                "run_id": speed_run_id,
                "parent_run_id": tracking_run_id,
                "video_id": video_id,
                "model_version": None,
                "config_hash": config_hash(config),
                "config_json": canonical_json(config),
                "schema_version": schema_version(),
                "code_version": current_code_version(tmp_path),
                "source_video_sha256": "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
                "started_at": _utc_now(),
                "status": "completed",
                "notes": "Synthetic software fixture speed estimation run",
            },
        )

        # Calibration run
        insert_run(
            conn,
            {
                "run_id": calib_run_id,
                "parent_run_id": None,
                "video_id": video_id,
                "model_version": None,
                "config_hash": config_hash(config),
                "config_json": canonical_json(config),
                "schema_version": schema_version(),
                "code_version": current_code_version(tmp_path),
                "source_video_sha256": "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
                "started_at": _utc_now(),
                "status": "completed",
                "notes": "Synthetic software fixture calibration run",
            },
        )

        parameters = {
            "homography_matrix": _SOFTWARE_H_TRUE.tolist(),
            "inverse_homography_matrix": _SOFTWARE_H_INV.tolist(),
            "coordinate_unit": "meter",
            "fit_point_count": 4,
            "held_out_point_count": 2,
            "reprojection_error_m_mean": 0.01,
            "reprojection_error_m_max": 0.02,
            "accepted": True,
        }
        insert_calibration_run(
            conn,
            {
                "calibration_id": accepted_calib_id,
                "run_id": calib_run_id,
                "video_id": video_id,
                "method": "planar_homography",
                "point_count": 6,
                "held_out_point_count": 2,
                "reprojection_error_m_mean": 0.01,
                "reprojection_error_m_max": 0.02,
                "distortion_checked": 0,
                "flat_road_assumption": 1,
                "accepted": 1,
                "parameters_json": json.dumps(parameters),
            },
        )

        insert_calibration_run(
            conn,
            {
                "calibration_id": rejected_calib_id,
                "run_id": calib_run_id,
                "video_id": video_id,
                "method": "planar_homography",
                "point_count": 6,
                "held_out_point_count": 2,
                "reprojection_error_m_mean": 2.5,
                "reprojection_error_m_max": 3.8,
                "distortion_checked": 0,
                "flat_road_assumption": 1,
                "accepted": 0,
                "parameters_json": json.dumps({**parameters, "accepted": False}),
            },
        )

        # Insert queue zone in pixel space covering world range [0..10, 0..30]
        # In image coords, vertices correspond roughly to [200, 500], [600, 500], [500, 200], [300, 200]
        insert_zone(
            conn,
            {
                "zone_id": "zone_north_queue",
                "video_id": video_id,
                "name": "North Approach Queue Zone",
                "zone_type": "queue",
                "approach": "north",
                "geometry_json": json.dumps({
                    "vertices": [
                        [150.0, 550.0],
                        [650.0, 550.0],
                        [550.0, 150.0],
                        [250.0, 150.0],
                    ]
                }),
                "config_version": "v1_synthetic",
                "geometry_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            },
        )

        # Insert approach stop line at world Y = 0 (image ~ [200, 500] to [600, 500])
        insert_counting_line(
            conn,
            {
                "line_id": "line_north_stop",
                "video_id": video_id,
                "name": "North Stop Line",
                "approach": "north",
                "geometry_json": json.dumps({
                    "endpoints": [[200.0, 500.0], [600.0, 500.0]],
                    "direction_vector": [0.0, 1.0],
                }),
                "bidirectional": 0,
                "config_version": "v1_synthetic",
                "geometry_sha256": "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
            },
        )

        # Populate tracks and speed observations for 3 vehicles over t=0.0..5.0
        # Track 1: Stopped at world (5.0, 5.0)
        # Track 2: Stopped at world (5.0, 15.0)
        # Track 3: Moving at 40 km/h
        track_rows = []
        speed_rows = []

        for fn in range(6):
            t_s = float(fn)

            # Track 1: stationary at (5.0, 5.0)
            u1, v1 = project_world_to_image(5.0, 5.0, _SOFTWARE_H_INV)
            track_rows.append({
                "track_observation_id": str(uuid4()),
                "run_id": tracking_run_id,
                "video_id": video_id,
                "track_id": 1,
                "frame_number": fn,
                "timestamp_s": t_s,
                "vehicle_class": "car",
                "confidence": 0.95,
                "x1": u1 - 20.0,
                "y1": v1 - 40.0,
                "x2": u1 + 20.0,
                "y2": v1,
                "ground_x": u1,
                "ground_y": v1,
                "world_x": 5.0,
                "world_y": 5.0,
                "calibration_id": accepted_calib_id,
                "trajectory_status": "complete",
            })
            speed_rows.append({
                "speed_observation_id": str(uuid4()),
                "run_id": speed_run_id,
                "video_id": video_id,
                "track_id": 1,
                "timestamp_s": t_s,
                "speed_mps": 0.0,
                "speed_kmh": 0.0,
                "calibration_id": accepted_calib_id,
                "status": "valid",
                "smoothing_window": 0.5,
                "ground_point_method": "bottom_center",
            })

            # Track 2: stationary at (5.0, 15.0)
            u2, v2 = project_world_to_image(5.0, 15.0, _SOFTWARE_H_INV)
            track_rows.append({
                "track_observation_id": str(uuid4()),
                "run_id": tracking_run_id,
                "video_id": video_id,
                "track_id": 2,
                "frame_number": fn,
                "timestamp_s": t_s,
                "vehicle_class": "car",
                "confidence": 0.95,
                "x1": u2 - 20.0,
                "y1": v2 - 40.0,
                "x2": u2 + 20.0,
                "y2": v2,
                "ground_x": u2,
                "ground_y": v2,
                "world_x": 5.0,
                "world_y": 15.0,
                "calibration_id": accepted_calib_id,
                "trajectory_status": "complete",
            })
            speed_rows.append({
                "speed_observation_id": str(uuid4()),
                "run_id": speed_run_id,
                "video_id": video_id,
                "track_id": 2,
                "timestamp_s": t_s,
                "speed_mps": 0.0,
                "speed_kmh": 0.0,
                "calibration_id": accepted_calib_id,
                "status": "valid",
                "smoothing_window": 0.5,
                "ground_point_method": "bottom_center",
            })

            # Track 3: moving at 40 km/h (11.1 m/s)
            u3, v3 = project_world_to_image(5.0, 2.0 + fn * 2.0, _SOFTWARE_H_INV)
            track_rows.append({
                "track_observation_id": str(uuid4()),
                "run_id": tracking_run_id,
                "video_id": video_id,
                "track_id": 3,
                "frame_number": fn,
                "timestamp_s": t_s,
                "vehicle_class": "car",
                "confidence": 0.95,
                "x1": u3 - 20.0,
                "y1": v3 - 40.0,
                "x2": u3 + 20.0,
                "y2": v3,
                "ground_x": u3,
                "ground_y": v3,
                "world_x": 5.0,
                "world_y": 2.0 + fn * 2.0,
                "calibration_id": accepted_calib_id,
                "trajectory_status": "complete",
            })
            speed_rows.append({
                "speed_observation_id": str(uuid4()),
                "run_id": speed_run_id,
                "video_id": video_id,
                "track_id": 3,
                "timestamp_s": t_s,
                "speed_mps": 11.11,
                "speed_kmh": 40.0,
                "calibration_id": accepted_calib_id,
                "status": "valid",
                "smoothing_window": 0.5,
                "ground_point_method": "bottom_center",
            })

        insert_tracks(conn, track_rows)
        insert_speed_observations(conn, speed_rows)
        conn.commit()

    return {
        "db_path": db_path,
        "video_id": video_id,
        "tracking_run_id": tracking_run_id,
        "speed_run_id": speed_run_id,
        "accepted_calib_id": accepted_calib_id,
        "rejected_calib_id": rejected_calib_id,
        "config": config,
    }


def test_tp9_12_database_persistence_and_provenance(queue_test_env: dict[str, Any]) -> None:
    """TP9-12: stop_events and queue_events retain run_id, video_id, timestamp_s, and FKs to parent run."""
    config = queue_test_env["config"]
    speed_run_id = queue_test_env["speed_run_id"]
    db_path = queue_test_env["db_path"]

    result = run_queue_detection(
        parent_run_id=speed_run_id,
        config=config,
    )
    queue_run_id = result["run_id"]
    assert result["stop_event_count"] == 2
    assert result["queue_event_count"] >= 1

    with database_connection(db_path) as conn:
        # Check child processing run record
        run_row = fetch_run_by_id(conn, queue_run_id)
        assert run_row is not None
        assert run_row["parent_run_id"] == speed_run_id
        assert run_row["video_id"] == queue_test_env["video_id"]
        assert run_row["status"] == "completed"
        assert run_row["started_at"] is not None
        assert run_row["completed_at"] is not None

        # Check stop_events table
        stop_rows = fetch_stop_events_for_run(conn, queue_run_id)
        assert len(stop_rows) == 2
        for s in stop_rows:
            assert s["run_id"] == queue_run_id
            assert s["video_id"] == queue_test_env["video_id"]
            assert s["track_id"] in (1, 2)
            assert s["status"] == "valid"
            assert s["duration_s"] == 5.0
            assert s["threshold_kmh"] == 5.0

        # Check queue_events table
        queue_rows = fetch_queue_events_for_run(conn, queue_run_id)
        assert len(queue_rows) == 6  # t = 0..5 (6 sample instants)
        for q in queue_rows:
            assert q["run_id"] == queue_run_id
            assert q["video_id"] == queue_test_env["video_id"]
            assert q["zone_id"] == "zone_north_queue"
            assert q["approach"] == "north"
            assert q["queued_vehicle_count"] == 2
            assert q["status"] == "valid"
            # Distance from stop line at Y=0 to rear-most vehicle (track 2 at Y=15) is 15.0m
            assert q["queue_length_m"] == pytest.approx(15.0, rel=1e-2)


def test_tp9_13_unaccepted_calibration_rejection(queue_test_env: dict[str, Any]) -> None:
    """TP9-13: Service rejects unaccepted calibration runs (accepted = 0)."""
    config = queue_test_env["config"]
    speed_run_id = queue_test_env["speed_run_id"]
    rejected_calib_id = queue_test_env["rejected_calib_id"]

    with pytest.raises(ValueError, match="is not accepted"):
        run_queue_detection(
            parent_run_id=speed_run_id,
            calibration_id=rejected_calib_id,
            config=config,
        )


def test_missing_or_incomplete_parent_run(queue_test_env: dict[str, Any]) -> None:
    """Service rejects non-existent or uncompleted parent processing runs."""
    config = queue_test_env["config"]
    db_path = queue_test_env["db_path"]

    # Non-existent run
    with pytest.raises(ValueError, match="does not exist"):
        run_queue_detection(parent_run_id=str(uuid4()), config=config)

    # Incomplete parent run
    running_id = str(uuid4())
    with database_connection(db_path) as conn:
        insert_run(
            conn,
            {
                "run_id": running_id,
                "parent_run_id": None,
                "video_id": queue_test_env["video_id"],
                "model_version": None,
                "config_hash": "dummy_hash",
                "config_json": "{}",
                "schema_version": schema_version(),
                "code_version": "dummy_code",
                "source_video_sha256": "abcdef",
                "started_at": _utc_now(),
                "status": "running",
                "notes": "Running run",
            },
        )
        conn.commit()

    with pytest.raises(ValueError, match="is not completed"):
        run_queue_detection(parent_run_id=running_id, config=config)


def test_tp9_15_cli_commands_end_to_end(queue_test_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """TP9-15: CLI commands detect-queue, show-queue, and show-stops execute end-to-end returning valid JSON."""
    speed_run_id = queue_test_env["speed_run_id"]
    config = queue_test_env["config"]
    config_path = queue_test_env["db_path"].parent / "test_config.yaml"

    import yaml
    with config_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(config, f)

    # 1. Test detect-queue
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "traffic-vision",
            "detect-queue",
            speed_run_id,
            "--config",
            str(config_path),
        ],
    )
    main()
    captured = capsys.readouterr()
    res = json.loads(captured.out)
    assert "run_id" in res
    assert res["stop_event_count"] == 2
    assert res["queue_event_count"] == 6
    queue_run_id = res["run_id"]

    # 2. Test show-queue
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "traffic-vision",
            "show-queue",
            queue_run_id,
            "--config",
            str(config_path),
        ],
    )
    main()
    captured_q = capsys.readouterr()
    res_q = json.loads(captured_q.out)
    assert res_q["run_id"] == queue_run_id
    assert res_q["count"] == 6
    assert len(res_q["queue_events"]) == 6

    # 3. Test show-stops
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "traffic-vision",
            "show-stops",
            queue_run_id,
            "--config",
            str(config_path),
        ],
    )
    main()
    captured_s = capsys.readouterr()
    res_s = json.loads(captured_s.out)
    assert res_s["run_id"] == queue_run_id
    assert res_s["count"] == 2
    assert len(res_s["stop_events"]) == 2


def test_get_queue_summary_and_query_filters(queue_test_env: dict[str, Any]) -> None:
    """Query APIs get_queue_summary, get_stop_events, and get_queue_events support expected filters."""
    config = queue_test_env["config"]
    speed_run_id = queue_test_env["speed_run_id"]

    result = run_queue_detection(parent_run_id=speed_run_id, config=config)
    queue_run_id = result["run_id"]

    # Summary
    summary = get_queue_summary(queue_run_id, config=config)
    assert summary["run_id"] == queue_run_id
    assert summary["stats"]["total_stops"] == 2
    assert summary["stats"]["valid_stops"] == 2
    assert summary["stats"]["total_queue_events"] == 6
    assert summary["stats"]["max_queued_vehicles"] == 2

    # Stop events with track_id filter and limit
    stops_filtered = get_stop_events(queue_run_id, track_id=1, limit=1, config=config)
    assert stops_filtered["count"] == 1
    assert stops_filtered["stop_events"][0]["track_id"] == 1

    # Queue events with zone_id filter and limit
    queues_filtered = get_queue_events(queue_run_id, zone_id="zone_north_queue", limit=2, config=config)
    assert queues_filtered["count"] == 2
    assert queues_filtered["queue_events"][0]["zone_id"] == "zone_north_queue"
