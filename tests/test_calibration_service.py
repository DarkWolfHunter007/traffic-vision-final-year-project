"""Integration tests for Phase 07 camera calibration service, persistence, and CLI.

Covers test plan criteria:
- TP7-08: Invariants and flags (flat_road_assumption=1, distortion_checked) recorded in calibration_runs.
- TP7-09: Persistence to calibration_runs and calibration_points with foreign keys and point roles.
- TP7-11: CLI commands traffic-vision calibrate and traffic-vision show-calibration.

NOTE: All calibration points and coordinates in this file are synthetic
software test fixtures generated for deterministic testing; they are not
traffic measurements from Pattom Intersection or real-world survey data.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any
from uuid import uuid4

import cv2
import numpy as np
import pytest
import yaml

from backend.cli import main
from backend.config import canonical_json, config_hash, load_config
from backend.database.connection import bootstrap_database, database_connection, schema_version
from backend.database.repository import (
    fetch_calibration_points_for_run,
    fetch_calibration_run_by_id,
    fetch_latest_accepted_calibration,
    insert_run,
    insert_video,
)
from backend.services.calibration import (
    get_calibration,
    load_calibration_points,
    run_calibration,
)
from backend.services.ingestion import _utc_now, current_code_version


# Software test fixture: synthetic ground-plane mapping
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


def _generate_software_fixture_point(u: float, v: float, role: str = "fit") -> dict[str, float | str]:
    vec = np.array([u, v, 1.0], dtype=np.float64)
    proj = _SOFTWARE_H_TRUE @ vec
    w = proj[2]
    return {
        "image_x": float(u),
        "image_y": float(v),
        "world_x": float(proj[0] / w),
        "world_y": float(proj[1] / w),
        "role": role,
    }


def get_software_fixture_points() -> list[dict[str, float | str]]:
    return [
        _generate_software_fixture_point(200.0, 500.0, role="fit"),
        _generate_software_fixture_point(600.0, 500.0, role="fit"),
        _generate_software_fixture_point(500.0, 200.0, role="fit"),
        _generate_software_fixture_point(300.0, 200.0, role="fit"),
        _generate_software_fixture_point(400.0, 350.0, role="held_out"),
        _generate_software_fixture_point(350.0, 420.0, role="held_out"),
    ]


@pytest.fixture
def test_env_setup(tmp_path: Path) -> tuple[Path, str, str, dict[str, Any]]:
    """Set up a disposable database and registered synthetic video and ingestion run."""
    db_path = tmp_path / "calibration_test.sqlite3"
    bootstrap_database(db_path)

    video_id = "vid_synthetic_pattom_fixture"
    parent_run_id = str(uuid4())

    config = load_config(overrides={"paths": {"database_path": str(db_path)}})

    with database_connection(db_path) as conn:
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
                "duration_s": 60.0,
                "frame_count": 1800,
                "variable_frame_rate": 0,
                "wall_clock_start": None,
                "ingested_at": _utc_now(),
                "metadata_json": None,
            },
        )
        insert_run(
            conn,
            {
                "run_id": parent_run_id,
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
                "notes": "Synthetic software fixture ingestion run",
            },
        )

    return db_path, video_id, parent_run_id, config


def test_tp7_08_and_09_database_persistence_and_invariants(
    test_env_setup: tuple[Path, str, str, dict[str, Any]],
    tmp_path: Path,
) -> None:
    """TP7-08 & TP7-09: Flags recorded and records persisted to calibration_runs and calibration_points."""
    db_path, video_id, parent_run_id, config = test_env_setup
    points = get_software_fixture_points()

    summary = run_calibration(
        parent_run_or_video_id=parent_run_id,
        points_file_or_data=points,
        config=config,
        repository_root=tmp_path,
    )

    assert summary["accepted"] is True
    assert summary["point_count"] == 6
    assert summary["held_out_point_count"] == 2
    assert summary["distortion_checked"] is False
    assert summary["flat_road_assumption"] is True
    calib_id = summary["calibration_id"]
    child_run_id = summary["run_id"]

    # Verify calibration_runs record in SQLite
    with database_connection(db_path) as conn:
        run_row = fetch_calibration_run_by_id(conn, calib_id)
        assert run_row is not None
        assert run_row["calibration_id"] == calib_id
        assert run_row["run_id"] == child_run_id
        assert run_row["video_id"] == video_id
        assert run_row["method"] == "planar_homography"
        assert run_row["point_count"] == 6
        assert run_row["held_out_point_count"] == 2
        assert run_row["reprojection_error_m_mean"] < 1e-4
        assert run_row["reprojection_error_m_max"] < 1e-4
        assert run_row["distortion_checked"] == 0
        assert run_row["flat_road_assumption"] == 1
        assert run_row["accepted"] == 1

        # Verify calibration_points records
        pts_rows = fetch_calibration_points_for_run(conn, calib_id)
        assert len(pts_rows) == 6
        fit_rows = [p for p in pts_rows if p["role"] == "fit"]
        held_out_rows = [p for p in pts_rows if p["role"] == "held_out"]
        assert len(fit_rows) == 4
        assert len(held_out_rows) == 2

        # Verify fetch_latest_accepted_calibration
        latest = fetch_latest_accepted_calibration(conn, video_id)
        assert latest is not None
        assert latest["calibration_id"] == calib_id


def test_tracks_world_coordinate_database_invariants(
    test_env_setup: tuple[Path, str, str, dict[str, Any]],
) -> None:
    """Verify schema integrity: world coordinates in tracks require a calibration reference."""
    db_path, video_id, parent_run_id, _ = test_env_setup

    with database_connection(db_path) as conn:
        # 1. tracks row with world_x, world_y and calibration_id=NULL violates CHECK constraint
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO tracks (
                    track_observation_id, run_id, video_id, track_id, frame_number,
                    timestamp_s, vehicle_class, confidence, x1, y1, x2, y2,
                    ground_x, ground_y, world_x, world_y, calibration_id, trajectory_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()), parent_run_id, video_id, 1, 0,
                    0.0, "car", 0.9, 100.0, 100.0, 150.0, 150.0,
                    125.0, 150.0, 5.0, 10.0, None, "complete",
                ),
            )

        # 2. tracks row with invalid calibration_id violates foreign key constraint
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO tracks (
                    track_observation_id, run_id, video_id, track_id, frame_number,
                    timestamp_s, vehicle_class, confidence, x1, y1, x2, y2,
                    ground_x, ground_y, world_x, world_y, calibration_id, trajectory_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()), parent_run_id, video_id, 1, 0,
                    0.0, "car", 0.9, 100.0, 100.0, 150.0, 150.0,
                    125.0, 150.0, 5.0, 10.0, "nonexistent_calib_id", "complete",
                ),
            )


def test_run_calibration_from_yaml_file_and_get_calibration(
    test_env_setup: tuple[Path, str, str, dict[str, Any]],
    tmp_path: Path,
) -> None:
    """Test loading points from YAML file and inspecting via get_calibration."""
    db_path, video_id, parent_run_id, config = test_env_setup
    points = get_software_fixture_points()

    yaml_path = tmp_path / "synthetic_points.yaml"
    yaml_path.write_text(yaml.safe_dump({"points": points}), encoding="utf-8")

    # Load points helper test
    loaded = load_calibration_points(yaml_path)
    assert len(loaded) == 6

    # Run calibration
    res = run_calibration(
        parent_run_or_video_id=video_id,  # Testing video_id target resolution
        points_file_or_data=yaml_path,
        config=config,
        repository_root=tmp_path,
    )
    assert res["accepted"] is True
    calib_id = res["calibration_id"]

    # Retrieve via get_calibration
    details = get_calibration(calib_id, config=config, repository_root=tmp_path)
    assert details is not None
    assert details["calibration_id"] == calib_id
    assert details["method"] == "planar_homography"
    assert "homography_matrix" in details["parameters"]
    assert "inverse_homography_matrix" in details["parameters"]
    assert len(details["points"]) == 6


def test_run_calibration_target_resolution_errors(
    test_env_setup: tuple[Path, str, str, dict[str, Any]],
    tmp_path: Path,
) -> None:
    """Test error handling when target run or video does not exist."""
    _, _, _, config = test_env_setup
    points = get_software_fixture_points()

    with pytest.raises(ValueError, match="is neither a known run_id nor video_id"):
        run_calibration(
            parent_run_or_video_id="unknown_target_id",
            points_file_or_data=points,
            config=config,
            repository_root=tmp_path,
        )


def test_tp7_11_cli_calibration_commands(
    test_env_setup: tuple[Path, str, str, dict[str, Any]],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TP7-11: CLI commands traffic-vision calibrate and traffic-vision show-calibration."""
    db_path, video_id, parent_run_id, _ = test_env_setup
    points = get_software_fixture_points()

    points_file = tmp_path / "cli_points.yaml"
    points_file.write_text(yaml.safe_dump(points), encoding="utf-8")

    config_file = tmp_path / "cli_config.yaml"
    cfg_data = load_config(overrides={"paths": {"database_path": str(db_path)}})
    config_file.write_text(yaml.safe_dump(cfg_data), encoding="utf-8")

    # 1. Test CLI calibrate
    stdout_buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout_buf)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "traffic-vision",
            "calibrate",
            parent_run_id,
            str(points_file),
            "--config",
            str(config_file),
        ],
    )
    main()

    output = stdout_buf.getvalue().strip()
    calib_json = json.loads(output)
    assert "calibration_id" in calib_json
    assert calib_json["accepted"] is True
    assert calib_json["point_count"] == 6
    calib_id = calib_json["calibration_id"]

    # 2. Test CLI show-calibration
    stdout_buf2 = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stdout_buf2)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "traffic-vision",
            "show-calibration",
            calib_id,
            "--config",
            str(config_file),
        ],
    )
    main()

    show_output = stdout_buf2.getvalue().strip()
    show_json = json.loads(show_output)
    assert show_json["calibration_id"] == calib_id
    assert show_json["accepted"] is True
    assert len(show_json["points"]) == 6
    assert "homography_matrix" in show_json["parameters"]
