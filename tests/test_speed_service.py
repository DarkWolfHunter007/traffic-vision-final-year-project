"""Phase 08 integration tests for speed estimation service, database persistence, and CLI.

All test fixtures in this module are synthetic software fixtures, explicitly
labelled as such. No real-world research measurements or calibration points
are fabricated.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from typing import Any
from uuid import uuid4

import cv2
import numpy as np
import pytest

from backend.calibration import project_world_to_image
from backend.config import canonical_json, config_hash, load_config
from backend.database.connection import (
    bootstrap_database,
    database_connection,
    schema_version,
)
from backend.database.repository import (
    fetch_run_by_id,
    fetch_speed_observation_stats,
    fetch_speed_observations_for_run,
    insert_calibration_points,
    insert_calibration_run,
    insert_run,
    insert_tracks,
    insert_video,
)
from backend.services.ingestion import _utc_now, current_code_version
from backend.services.speed import get_speed_observations, run_speed_estimation

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
def speed_test_env(tmp_path: Path) -> dict[str, Any]:
    """Set up database with synthetic video, tracking run, tracks, and calibration run."""
    db_path = tmp_path / "speed_test.sqlite3"
    bootstrap_database(db_path)

    video_id = "vid_synthetic_speed_fixture"
    tracking_run_id = str(uuid4())
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

        # Calibration parent run
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

        # Accepted calibration
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

        # Rejected calibration
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

        # Populate synthetic tracks for 2 vehicles
        # Track 1: Moving at 10.0 m/s (36.0 km/h) for 5 frames (dt = 0.1s)
        # Track 2: Stationary vehicle at (5.0, 15.0) for 4 frames
        track_rows = []
        for fn in range(5):
            t_s = fn * 0.1
            world_x = 5.0
            world_y = fn * 1.0  # 1.0 m per 0.1 s = 10 m/s
            u, v = project_world_to_image(world_x, world_y, _SOFTWARE_H_INV)
            track_rows.append({
                "track_observation_id": str(uuid4()),
                "run_id": tracking_run_id,
                "video_id": video_id,
                "track_id": 1,
                "frame_number": fn,
                "timestamp_s": t_s,
                "vehicle_class": "car",
                "confidence": 0.95,
                "x1": u - 20.0,
                "y1": v - 40.0,
                "x2": u + 20.0,
                "y2": v,
                "ground_x": u,
                "ground_y": v,
                "world_x": None,
                "world_y": None,
                "calibration_id": None,
                "trajectory_status": "complete",
            })

        for fn in range(4):
            t_s = fn * 0.1
            world_x = 5.0
            world_y = 15.0  # stationary
            u, v = project_world_to_image(world_x, world_y, _SOFTWARE_H_INV)
            track_rows.append({
                "track_observation_id": str(uuid4()),
                "run_id": tracking_run_id,
                "video_id": video_id,
                "track_id": 2,
                "frame_number": fn,
                "timestamp_s": t_s,
                "vehicle_class": "auto_rickshaw",
                "confidence": 0.90,
                "x1": u - 15.0,
                "y1": v - 30.0,
                "x2": u + 15.0,
                "y2": v,
                "ground_x": u,
                "ground_y": v,
                "world_x": None,
                "world_y": None,
                "calibration_id": None,
                "trajectory_status": "complete",
            })

        insert_tracks(conn, track_rows)

    return {
        "db_path": db_path,
        "video_id": video_id,
        "tracking_run_id": tracking_run_id,
        "accepted_calib_id": accepted_calib_id,
        "rejected_calib_id": rejected_calib_id,
        "config": config,
        "tmp_path": tmp_path,
    }


def test_tp8_11_database_persistence_and_provenance(speed_test_env: dict[str, Any]) -> None:
    """TP8-11: Speed observations persisted with exact provenance and canonical schema."""
    env = speed_test_env
    summary = run_speed_estimation(
        parent_run_id=env["tracking_run_id"],
        calibration_id=env["accepted_calib_id"],
        config=env["config"],
        repository_root=env["tmp_path"],
    )

    assert summary["trajectory_count"] == 2
    assert summary["total_observations"] == 9  # 5 from track 1 + 4 from track 2
    assert summary["valid_count"] == 7        # (5-1) + (4-1) = 4 + 3 = 7
    assert summary["unavailable_count"] == 2  # initial points for both tracks
    assert summary["invalid_count"] == 0
    assert summary["mean_speed_kmh"] is not None

    speed_run_id = summary["run_id"]

    with database_connection(env["db_path"]) as conn:
        # Check child processing_runs record
        run_row = fetch_run_by_id(conn, speed_run_id)
        assert run_row is not None
        assert run_row["parent_run_id"] == env["tracking_run_id"]
        assert run_row["video_id"] == env["video_id"]
        assert run_row["status"] == "completed"

        # Check speed_observations table in SQLite
        obs_rows = fetch_speed_observations_for_run(conn, speed_run_id)
        assert len(obs_rows) == 9

        for row in obs_rows:
            assert row["run_id"] == speed_run_id
            assert row["video_id"] == env["video_id"]
            assert row["calibration_id"] == env["accepted_calib_id"]
            assert row["ground_point_method"] == "bottom_center"
            assert row["status"] in ("valid", "unavailable")

            if row["status"] == "valid":
                assert row["speed_mps"] is not None
                assert row["speed_kmh"] is not None
                assert abs(row["speed_kmh"] - row["speed_mps"] * 3.6) < 1e-3
            else:
                assert row["speed_mps"] is None
                assert row["speed_kmh"] is None

        # Check track 2 (stationary)
        track_2_obs = fetch_speed_observations_for_run(conn, speed_run_id, track_id=2)
        assert len(track_2_obs) == 4
        # Points 1, 2, 3 should have speed = 0.0
        for obs in track_2_obs[1:]:
            assert obs["status"] == "valid"
            assert obs["speed_mps"] == 0.0
            assert obs["speed_kmh"] == 0.0


def test_tp8_12_unaccepted_and_missing_calibration_rejected(speed_test_env: dict[str, Any]) -> None:
    """TP8-12: Unaccepted calibration or missing calibration triggers ValueError."""
    env = speed_test_env

    # 1. Attempt speed estimation with rejected calibration (accepted = 0)
    with pytest.raises(ValueError, match="not accepted"):
        run_speed_estimation(
            parent_run_id=env["tracking_run_id"],
            calibration_id=env["rejected_calib_id"],
            config=env["config"],
            repository_root=env["tmp_path"],
        )

    # 2. Attempt with non-existent calibration ID
    with pytest.raises(ValueError, match="not found"):
        run_speed_estimation(
            parent_run_id=env["tracking_run_id"],
            calibration_id="non_existent_calib_uuid",
            config=env["config"],
            repository_root=env["tmp_path"],
        )


def test_auto_resolve_latest_accepted_calibration(speed_test_env: dict[str, Any]) -> None:
    """Test omitting calibration_id automatically selects latest accepted calibration."""
    env = speed_test_env
    summary = run_speed_estimation(
        parent_run_id=env["tracking_run_id"],
        calibration_id=None,  # omitted
        config=env["config"],
        repository_root=env["tmp_path"],
    )
    assert summary["calibration_id"] == env["accepted_calib_id"]
    assert summary["valid_count"] == 7


def test_missing_parent_run_rejected(speed_test_env: dict[str, Any]) -> None:
    """Test non-existent parent run ID is rejected."""
    env = speed_test_env
    with pytest.raises(ValueError, match="Parent processing run does not exist"):
        run_speed_estimation(
            parent_run_id="non_existent_run_id",
            calibration_id=env["accepted_calib_id"],
            config=env["config"],
            repository_root=env["tmp_path"],
        )


def test_tp8_13_service_end_to_end_and_cli_commands(speed_test_env: dict[str, Any]) -> None:
    """TP8-13: CLI commands estimate-speed and show-speed produce valid JSON output."""
    env = speed_test_env
    config_path = env["tmp_path"] / "cli_test_config.yaml"
    import yaml
    config_path.write_text(yaml.dump(env["config"]), encoding="utf-8")

    # Run estimate-speed CLI command
    cmd_estimate = [
        sys.executable,
        "-m",
        "backend.cli",
        "estimate-speed",
        env["tracking_run_id"],
        "--calibration-id",
        env["accepted_calib_id"],
        "--config",
        str(config_path),
    ]
    proc_est = subprocess.run(cmd_estimate, capture_output=True, text=True, check=True)
    out_est = json.loads(proc_est.stdout.strip())

    assert "run_id" in out_est
    assert out_est["parent_run_id"] == env["tracking_run_id"]
    assert out_est["total_observations"] == 9
    assert out_est["valid_count"] == 7

    speed_run_id = out_est["run_id"]

    # Run show-speed CLI command
    cmd_show = [
        sys.executable,
        "-m",
        "backend.cli",
        "show-speed",
        speed_run_id,
        "--config",
        str(config_path),
    ]
    proc_show = subprocess.run(cmd_show, capture_output=True, text=True, check=True)
    out_show = json.loads(proc_show.stdout.strip())

    assert out_show["run_id"] == speed_run_id
    assert out_show["count"] == 9
    assert "stats" in out_show
    assert out_show["stats"]["valid_count"] == 7

    # Run show-speed with track filter and limit
    cmd_show_track = [
        sys.executable,
        "-m",
        "backend.cli",
        "show-speed",
        speed_run_id,
        "--track-id",
        "1",
        "--limit",
        "2",
        "--config",
        str(config_path),
    ]
    proc_show_track = subprocess.run(cmd_show_track, capture_output=True, text=True, check=True)
    out_show_track = json.loads(proc_show_track.stdout.strip())

    assert out_show_track["track_id"] == 1
    assert out_show_track["count"] == 2


# ---------------------------------------------------------------------------
# Phase 08 defect-fix tests (synthetic software fixtures)
# ---------------------------------------------------------------------------


def _insert_plain_run(conn: sqlite3.Connection, env: dict[str, Any], video_id: str, notes: str) -> str:
    run_id = str(uuid4())
    insert_run(
        conn,
        {
            "run_id": run_id,
            "parent_run_id": None,
            "video_id": video_id,
            "model_version": None,
            "config_hash": config_hash(env["config"]),
            "config_json": canonical_json(env["config"]),
            "schema_version": schema_version(),
            "code_version": current_code_version(env["tmp_path"]),
            "source_video_sha256": "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789",
            "started_at": _utc_now(),
            "status": "completed",
            "notes": notes,
        },
    )
    return run_id


def test_service_end_to_end_values(speed_test_env: dict[str, Any]) -> None:
    env = speed_test_env
    summary = run_speed_estimation(
        parent_run_id=env["tracking_run_id"],
        calibration_id=env["accepted_calib_id"],
        config=env["config"],
        repository_root=env["tmp_path"],
    )
    assert summary["max_speed_mps"] == pytest.approx(10.0, abs=1e-3)
    assert summary["max_speed_kmh"] == pytest.approx(36.0, abs=1e-2)
    with database_connection(env["db_path"]) as conn:
        rows = fetch_speed_observations_for_run(conn, summary["run_id"], track_id=1)
        for row in rows[1:]:
            assert row["status"] == "valid"
            assert row["speed_mps"] == pytest.approx(10.0, abs=1e-3)
            assert row["speed_kmh"] == pytest.approx(36.0, abs=1e-2)
            assert row["smoothing_window"] == 0.5


def test_smoothing_window_null_when_method_none(speed_test_env: dict[str, Any]) -> None:
    env = speed_test_env
    cfg = dict(env["config"])
    cfg["speed"] = {**cfg["speed"], "smoothing_method": "none"}
    summary = run_speed_estimation(
        parent_run_id=env["tracking_run_id"],
        calibration_id=env["accepted_calib_id"],
        config=cfg,
        repository_root=env["tmp_path"],
    )
    with database_connection(env["db_path"]) as conn:
        rows = fetch_speed_observations_for_run(conn, summary["run_id"])
        assert rows and all(r["smoothing_window"] is None for r in rows)


def test_calibration_from_other_video_rejected(speed_test_env: dict[str, Any]) -> None:
    env = speed_test_env
    other_video = "vid_other_fixture"
    with database_connection(env["db_path"]) as conn:
        insert_video(
            conn,
            {
                "video_id": other_video, "filename": "o.mp4", "path": str(env["tmp_path"] / "o.mp4"),
                "sha256": "0" * 64, "fps_nominal": 30.0, "width": 1920, "height": 1080,
                "duration_s": 1.0, "frame_count": 30, "variable_frame_rate": 0,
                "wall_clock_start": None, "ingested_at": _utc_now(), "metadata_json": None,
            },
        )
        other_run = _insert_plain_run(conn, env, other_video, "Synthetic software fixture calibration run")
        other_calib = str(uuid4())
        insert_calibration_run(
            conn,
            {
                "calibration_id": other_calib, "run_id": other_run, "video_id": other_video,
                "method": "planar_homography", "point_count": 6, "held_out_point_count": 2,
                "reprojection_error_m_mean": 0.01, "reprojection_error_m_max": 0.02,
                "distortion_checked": 0, "flat_road_assumption": 1, "accepted": 1,
                "parameters_json": json.dumps({"homography_matrix": _SOFTWARE_H_TRUE.tolist()}),
            },
        )
    with pytest.raises(ValueError, match="belongs to video"):
        run_speed_estimation(
            parent_run_id=env["tracking_run_id"], calibration_id=other_calib,
            config=env["config"], repository_root=env["tmp_path"],
        )


def test_auto_resolve_without_accepted_calibration_errors(speed_test_env: dict[str, Any]) -> None:
    env = speed_test_env
    with database_connection(env["db_path"]) as conn:
        conn.execute("UPDATE calibration_runs SET accepted = 0")
    with pytest.raises(ValueError, match="No accepted calibration"):
        run_speed_estimation(
            parent_run_id=env["tracking_run_id"], calibration_id=None,
            config=env["config"], repository_root=env["tmp_path"],
        )


def test_non_tracking_parent_rejected(speed_test_env: dict[str, Any]) -> None:
    env = speed_test_env
    with database_connection(env["db_path"]) as conn:
        non_tracking = _insert_plain_run(conn, env, env["video_id"], "Synthetic software fixture calibration run")
    with pytest.raises(ValueError, match="not a tracking run"):
        run_speed_estimation(
            parent_run_id=non_tracking, calibration_id=env["accepted_calib_id"],
            config=env["config"], repository_root=env["tmp_path"],
        )


def _failing_insert(conn: sqlite3.Connection, rows: Any) -> None:
    from backend.database.repository import insert_speed_observations as real_insert

    rows = list(rows)
    real_insert(conn, rows[:3])
    raise RuntimeError("software fixture insert failure")


def test_failed_insert_leaves_no_rows_and_run_failed(
    speed_test_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    env = speed_test_env
    monkeypatch.setattr("backend.services.speed.insert_speed_observations", _failing_insert)
    with pytest.raises(RuntimeError, match="insert failure"):
        run_speed_estimation(
            parent_run_id=env["tracking_run_id"], calibration_id=env["accepted_calib_id"],
            config=env["config"], repository_root=env["tmp_path"],
        )
    with database_connection(env["db_path"]) as conn:
        assert conn.execute("SELECT COUNT(*) FROM speed_observations").fetchone()[0] == 0
        failed = conn.execute(
            "SELECT status FROM processing_runs WHERE parent_run_id = ?", (env["tracking_run_id"],)
        ).fetchall()
        assert [r["status"] for r in failed] == ["failed"]


def test_failed_insert_preserves_caller_pending_work(
    speed_test_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    env = speed_test_env
    monkeypatch.setattr("backend.services.speed.insert_speed_observations", _failing_insert)
    conn = sqlite3.connect(env["db_path"])
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("UPDATE videos SET filename = 'pending_caller_change.mp4'")
        with pytest.raises(RuntimeError, match="insert failure"):
            run_speed_estimation(
                parent_run_id=env["tracking_run_id"], calibration_id=env["accepted_calib_id"],
                config=env["config"], repository_root=env["tmp_path"], connection=conn,
            )
        assert conn.execute("SELECT COUNT(*) FROM speed_observations").fetchone()[0] == 0
        assert conn.execute("SELECT filename FROM videos").fetchone()[0] == "pending_caller_change.mp4"
    finally:
        conn.close()
