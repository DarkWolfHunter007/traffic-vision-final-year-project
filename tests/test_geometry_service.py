"""Tests for Phase 05 geometry configuration service and CLI interfaces.

Software fixture notice: Test fixtures are synthetic software fixtures for validating
invariants and error handling; they do not represent real-world CCTV footage validation.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from typing import Any
import uuid

import cv2
import pytest
import yaml

from backend.cli import build_parser, main
from backend.database.connection import bootstrap_database, database_connection
from backend.database.repository import (
    fetch_counting_lines_for_video,
    fetch_zones_for_video,
)
from backend.geometry import point_side_of_line
from backend.media import inspect_video, sha256_file
from backend.services.geometry_config import (
    fetch_geometry_for_video,
    load_geometry_config,
    render_geometry_preview,
)
from backend.trajectories import build_trajectories


@pytest.fixture
def synthetic_video(tmp_path: Path) -> Path:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is required for the synthetic media fixture")
    video_path = tmp_path / "synthetic_geom.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=navy:s=640x480:r=10:d=1",
            "-pix_fmt",
            "yuv420p",
            str(video_path),
        ],
        check=True,
        capture_output=True,
    )
    return video_path


@pytest.fixture
def db_and_video(tmp_path: Path, synthetic_video: Path) -> tuple[Path, str, Path]:
    db_path = tmp_path / "traffic_test.sqlite3"
    bootstrap_database(db_path)
    video_meta = inspect_video(synthetic_video)
    video_sha = sha256_file(synthetic_video)
    video_id = "vid-phase05-test"

    with database_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO videos (
                video_id, filename, path, sha256, fps_nominal, width, height,
                duration_s, frame_count, ingested_at
            ) VALUES (?, 'synthetic_geom.mp4', ?, ?, ?, ?, ?, ?, ?, '2026-10-14T00:00:00Z')
            """,
            (
                video_id,
                str(synthetic_video),
                video_sha,
                video_meta.fps_nominal,
                video_meta.width,
                video_meta.height,
                video_meta.duration_s,
                video_meta.frame_count,
            ),
        )

    return db_path, video_id, synthetic_video


def test_tp5_05_idempotent_reload_preserves_existing_rows(
    tmp_path: Path, db_and_video: tuple[Path, str, Path]
) -> None:
    """TP5-05: Reloading identical geometry configuration is idempotent (preserves existing rows without duplicates)."""
    db_path, video_id, _ = db_and_video
    app_config = {"paths": {"database_path": str(db_path)}}

    geom_cfg = {
        "approaches": ["north", "south"],
        "counting_lines": [
            {
                "line_id": "line_north_in",
                "name": "North In",
                "approach": "north",
                "endpoints": [[100.0, 200.0], [300.0, 200.0]],
                "direction_vector": [0.0, 1.0],
                "bidirectional": False,
            },
            {
                "line_id": "line_south_out",
                "name": "South Out",
                "approach": "south",
                "endpoints": [[100.0, 400.0], [300.0, 400.0]],
                "direction_vector": None,
                "bidirectional": True,
            },
        ],
        "zones": [
            {
                "zone_id": "zone_north_entry",
                "name": "North Entry",
                "zone_type": "entry",
                "approach": "north",
                "vertices": [[50.0, 50.0], [350.0, 50.0], [350.0, 190.0], [50.0, 190.0]],
            },
            {
                "zone_id": "zone_south_exit",
                "name": "South Exit",
                "zone_type": "exit",
                "approach": "south",
                "vertices": [[50.0, 410.0], [350.0, 410.0], [350.0, 470.0], [50.0, 470.0]],
            },
        ],
    }

    cfg_file = tmp_path / "geom_test.yaml"
    with open(cfg_file, "w", encoding="utf-8") as f:
        yaml.dump(geom_cfg, f)

    # First load
    res1 = load_geometry_config(video_id, cfg_file, config=app_config)
    assert res1["counting_lines_count"] == 2
    assert res1["zones_count"] == 2
    assert res1["lines_inserted"] == 2
    assert res1["zones_inserted"] == 2

    with database_connection(db_path) as conn:
        lines1 = fetch_counting_lines_for_video(conn, video_id)
        zones1 = fetch_zones_for_video(conn, video_id)
        assert len(lines1) == 2
        assert len(zones1) == 2
        line_hashes_1 = {row["line_id"]: row["geometry_sha256"] for row in lines1}

    # Second reload with identical configuration
    res2 = load_geometry_config(video_id, cfg_file, config=app_config)
    assert res2["lines_inserted"] == 0
    assert res2["zones_inserted"] == 0

    with database_connection(db_path) as conn:
        lines2 = fetch_counting_lines_for_video(conn, video_id)
        zones2 = fetch_zones_for_video(conn, video_id)
        assert len(lines2) == 2
        assert len(zones2) == 2
        line_hashes_2 = {row["line_id"]: row["geometry_sha256"] for row in lines2}
        assert line_hashes_1 == line_hashes_2


def test_tp5_06_entry_exit_declared_approach_validation(
    tmp_path: Path, db_and_video: tuple[Path, str, Path]
) -> None:
    """TP5-06: Entry and exit zones assigned to a declared approach; zone referencing undeclared approach rejected."""
    db_path, video_id, _ = db_and_video
    app_config = {"paths": {"database_path": str(db_path)}}

    # Entry zone referencing undeclared approach 'east'
    cfg_undeclared = {
        "approaches": ["north", "south"],
        "zones": [
            {
                "zone_id": "z_invalid",
                "name": "Invalid East Entry",
                "zone_type": "entry",
                "approach": "east",
                "vertices": [[10.0, 10.0], [50.0, 10.0], [50.0, 50.0], [10.0, 50.0]],
            }
        ],
    }
    with pytest.raises(ValueError, match="not declared in approaches"):
        load_geometry_config(video_id, cfg_undeclared, config=app_config)

    # Entry zone missing approach
    cfg_missing_approach = {
        "approaches": ["north", "south"],
        "zones": [
            {
                "zone_id": "z_no_app",
                "name": "No Approach Entry",
                "zone_type": "entry",
                "approach": None,
                "vertices": [[10.0, 10.0], [50.0, 10.0], [50.0, 50.0], [10.0, 50.0]],
            }
        ],
    }
    with pytest.raises(ValueError, match="must be assigned to a declared approach"):
        load_geometry_config(video_id, cfg_missing_approach, config=app_config)

    # Exit zone missing approach
    cfg_exit_no_app = {
        "approaches": ["north", "south"],
        "zones": [
            {
                "zone_id": "z_exit_no_app",
                "name": "No Approach Exit",
                "zone_type": "exit",
                "approach": None,
                "vertices": [[10.0, 10.0], [50.0, 10.0], [50.0, 50.0], [10.0, 50.0]],
            }
        ],
    }
    with pytest.raises(ValueError, match="must be assigned to a declared approach"):
        load_geometry_config(video_id, cfg_exit_no_app, config=app_config)

    # Line referencing undeclared approach
    cfg_line_undeclared = {
        "approaches": ["north"],
        "counting_lines": [
            {
                "line_id": "l_bad",
                "name": "Bad Approach Line",
                "approach": "west",
                "endpoints": [[10.0, 10.0], [50.0, 10.0]],
                "direction_vector": [0.0, 1.0],
                "bidirectional": False,
            }
        ],
    }
    with pytest.raises(ValueError, match="undeclared approach 'west'"):
        load_geometry_config(video_id, cfg_line_undeclared, config=app_config)


def test_tp5_09_show_geometry_rendering_no_processing_run(
    tmp_path: Path, db_and_video: tuple[Path, str, Path]
) -> None:
    """TP5-09: Geometry rendering via show-geometry CLI produces an image overlay with lines and zones
    on a video frame, creating NO processing_run.
    """
    db_path, video_id, _ = db_and_video
    app_config = {"paths": {"database_path": str(db_path)}}

    cfg_data = {
        "approaches": ["north"],
        "counting_lines": [
            {
                "line_id": "line_north",
                "name": "North Counting Line",
                "approach": "north",
                "endpoints": [[100.0, 200.0], [400.0, 200.0]],
                "direction_vector": [0.0, 1.0],
                "bidirectional": False,
            }
        ],
        "zones": [
            {
                "zone_id": "zone_north",
                "name": "North Entry",
                "zone_type": "entry",
                "approach": "north",
                "vertices": [[80.0, 50.0], [420.0, 50.0], [420.0, 190.0], [80.0, 190.0]],
            }
        ],
    }
    load_geometry_config(video_id, cfg_data, config=app_config)

    out_image = tmp_path / "preview_overlay.png"
    result_path = render_geometry_preview(
        video_id=video_id,
        output_path=out_image,
        frame_number=0,
        config=app_config,
    )

    assert result_path.exists()
    assert result_path.stat().st_size > 0

    img = cv2.imread(str(result_path))
    assert img is not None
    assert img.shape == (480, 640, 3)

    # Invariant: show-geometry creates NO processing_run record
    with database_connection(db_path) as conn:
        run_count = conn.execute(
            "SELECT count(*) FROM processing_runs WHERE video_id = ?",
            (video_id,),
        ).fetchone()[0]
        assert run_count == 0


def test_tp5_10_trajectory_ground_points_against_counting_line_integration() -> None:
    """TP5-10: Integration test: Phase 04 trajectory ground points from build_trajectories()
    can be checked against a configured counting line using pure line-side helper.
    """
    # Horizontal counting line along y = 200, from (100, 200) to (400, 200)
    line_start = (100.0, 200.0)
    line_end = (400.0, 200.0)

    # Synthetic observations: vehicle moving southwards from y=120 to y=280 across line y=200
    observations = [
        {
            "track_observation_id": "obs-1",
            "run_id": "run-p04-int",
            "video_id": "vid-int",
            "track_id": 42,
            "frame_number": 0,
            "timestamp_s": 0.0,
            "vehicle_class": "car",
            "confidence": 0.95,
            "x1": 180.0,
            "y1": 80.0,
            "x2": 220.0,
            "y2": 120.0,
            "ground_x": 200.0,
            "ground_y": 120.0,  # Above line (y < 200)
            "world_x": None,
            "world_y": None,
            "calibration_id": None,
            "trajectory_status": "complete",
        },
        {
            "track_observation_id": "obs-2",
            "run_id": "run-p04-int",
            "video_id": "vid-int",
            "track_id": 42,
            "frame_number": 1,
            "timestamp_s": 0.1,
            "vehicle_class": "car",
            "confidence": 0.94,
            "x1": 180.0,
            "y1": 240.0,
            "x2": 220.0,
            "y2": 280.0,
            "ground_x": 200.0,
            "ground_y": 280.0,  # Below line (y > 200)
            "world_x": None,
            "world_y": None,
            "calibration_id": None,
            "trajectory_status": "complete",
        },
    ]

    trajectories = build_trajectories(
        observations=observations,
        video_width=640,
        video_height=480,
    )
    assert 42 in trajectories
    traj = trajectories[42]
    assert len(traj.points) == 2

    # Check trajectory ground points against counting line with pure line-side helper
    pt0 = (traj.points[0].ground_x, traj.points[0].ground_y)
    pt1 = (traj.points[1].ground_x, traj.points[1].ground_y)

    side_before = point_side_of_line(pt0, line_start, line_end)
    side_after = point_side_of_line(pt1, line_start, line_end)

    # Sign change demonstrates trajectory ground points can be checked against counting line
    assert side_before == -1
    assert side_after == 1
    assert side_before != side_after
    assert side_before * side_after == -1


def test_tp5_11_config_version_immutability(
    tmp_path: Path, db_and_video: tuple[Path, str, Path]
) -> None:
    """TP5-11: Config version immutability: modifying geometry for an existing version is rejected;
    changed geometry yields a new version.
    """
    db_path, video_id, _ = db_and_video
    app_config = {"paths": {"database_path": str(db_path)}}

    cfg_v1 = {
        "approaches": ["north"],
        "counting_lines": [
            {
                "line_id": "line_north",
                "name": "North Line",
                "approach": "north",
                "endpoints": [[100.0, 100.0], [300.0, 100.0]],
                "direction_vector": [0.0, 1.0],
                "bidirectional": False,
            }
        ],
    }

    load_geometry_config(video_id, cfg_v1, config=app_config)

    with database_connection(db_path) as conn:
        lines = fetch_counting_lines_for_video(conn, video_id)
        assert len(lines) == 1
        ver_1 = lines[0]["config_version"]
        hash_1 = lines[0]["geometry_sha256"]

    # Changing geometry for the same line_id is rejected to preserve immutability
    cfg_modified = {
        "approaches": ["north"],
        "counting_lines": [
            {
                "line_id": "line_north",
                "name": "North Line",
                "approach": "north",
                "endpoints": [[100.0, 100.0], [300.0, 150.0]],  # changed y2
                "direction_vector": [0.0, 1.0],
                "bidirectional": False,
            }
        ],
    }

    with pytest.raises(ValueError, match="Modifying geometry for an existing version is rejected"):
        load_geometry_config(video_id, cfg_modified, config=app_config)

    # Registering the modified geometry with a new line ID creates a new version
    cfg_v2 = {
        "approaches": ["north"],
        "counting_lines": [
            {
                "line_id": "line_north_v2",
                "name": "North Line v2",
                "approach": "north",
                "endpoints": [[100.0, 100.0], [300.0, 150.0]],
                "direction_vector": [0.0, 1.0],
                "bidirectional": False,
            }
        ],
    }

    load_geometry_config(video_id, cfg_v2, config=app_config)

    with database_connection(db_path) as conn:
        lines = fetch_counting_lines_for_video(conn, video_id)
        assert len(lines) == 2
        ver_2 = lines[1]["config_version"]
        hash_2 = lines[1]["geometry_sha256"]

        assert hash_1 != hash_2
        assert ver_1 != ver_2
        # Original version remains unmodified
        assert lines[0]["config_version"] == ver_1


def test_tp5_12_multiple_rois_and_out_of_bounds_rejection(
    tmp_path: Path, db_and_video: tuple[Path, str, Path]
) -> None:
    """TP5-12: Multiple ROIs per video accepted; geometry coordinates outside video frame boundaries rejected."""
    db_path, video_id, _ = db_and_video
    app_config = {"paths": {"database_path": str(db_path)}}

    # Multiple ROIs per video accepted
    cfg_multiple_rois = {
        "zones": [
            {
                "zone_id": "roi_main",
                "name": "Main ROI",
                "zone_type": "roi",
                "vertices": [[10.0, 10.0], [300.0, 10.0], [300.0, 300.0], [10.0, 300.0]],
            },
            {
                "zone_id": "roi_secondary",
                "name": "Secondary ROI",
                "zone_type": "roi",
                "vertices": [[320.0, 10.0], [600.0, 10.0], [600.0, 300.0], [320.0, 300.0]],
            },
        ]
    }
    load_geometry_config(video_id, cfg_multiple_rois, config=app_config)

    with database_connection(db_path) as conn:
        zones = fetch_zones_for_video(conn, video_id)
        assert len(zones) == 2
        assert all(z["zone_type"] == "roi" for z in zones)

    # Frame bounds: 640x480. Out-of-bounds coordinates rejected
    # 1. Polygon vertex with x > 640
    cfg_oob_polygon_x = {
        "zones": [
            {
                "zone_id": "roi_oob",
                "name": "OOB ROI",
                "zone_type": "roi",
                "vertices": [[10.0, 10.0], [650.0, 10.0], [650.0, 300.0], [10.0, 300.0]],
            }
        ]
    }
    with pytest.raises(ValueError, match="outside video frame bounds"):
        load_geometry_config(video_id, cfg_oob_polygon_x, config=app_config)

    # 2. Polygon vertex with y < 0
    cfg_oob_polygon_y = {
        "zones": [
            {
                "zone_id": "roi_oob_neg",
                "name": "OOB Neg ROI",
                "zone_type": "roi",
                "vertices": [[10.0, -5.0], [100.0, -5.0], [100.0, 100.0], [10.0, 100.0]],
            }
        ]
    }
    with pytest.raises(ValueError, match="outside video frame bounds"):
        load_geometry_config(video_id, cfg_oob_polygon_y, config=app_config)

    # 3. Counting line endpoint with y > 480
    cfg_oob_line = {
        "counting_lines": [
            {
                "line_id": "line_oob",
                "name": "OOB Line",
                "endpoints": [[100.0, 100.0], [100.0, 500.0]],
                "direction_vector": [1.0, 0.0],
                "bidirectional": False,
            }
        ]
    }
    with pytest.raises(ValueError, match="outside video frame bounds"):
        load_geometry_config(video_id, cfg_oob_line, config=app_config)


def test_cli_load_geometry_and_show_geometry(
    tmp_path: Path,
    db_and_video: tuple[Path, str, Path],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test CLI commands 'load-geometry' and 'show-geometry'."""
    db_path, video_id, _ = db_and_video

    cli_cfg = tmp_path / "cli_config.yaml"
    with open(cli_cfg, "w", encoding="utf-8") as f:
        yaml.dump(
            {
                "paths": {
                    "raw_root": "data/raw",
                    "processed_root": str(tmp_path),
                    "database_path": str(db_path),
                },
                "input": {"supported_formats": [".mp4"]},
                "timestamp": {"strategy": "decoder_pts"},
                "streaming": {"frame_batch_size": 500, "preview_frame_number": 0},
                "resources": {"policy": "cpu"},
                "logging": {"level": "WARNING"},
            },
            f,
        )

    geom_file = tmp_path / "cli_geom.yaml"
    with open(geom_file, "w", encoding="utf-8") as f:
        yaml.dump(
            {
                "approaches": ["north"],
                "counting_lines": [
                    {
                        "line_id": "line_cli",
                        "name": "CLI Line",
                        "approach": "north",
                        "endpoints": [[100.0, 200.0], [300.0, 200.0]],
                        "direction_vector": [0.0, 1.0],
                        "bidirectional": False,
                    }
                ],
                "zones": [
                    {
                        "zone_id": "zone_cli",
                        "name": "CLI Zone",
                        "zone_type": "entry",
                        "approach": "north",
                        "vertices": [[50.0, 50.0], [350.0, 50.0], [350.0, 180.0], [50.0, 180.0]],
                    }
                ],
            },
            f,
        )

    # 1. Test load-geometry CLI command
    monkeypatch.setattr(
        "sys.argv",
        [
            "traffic-vision",
            "load-geometry",
            video_id,
            str(geom_file),
            "--config",
            str(cli_cfg),
        ],
    )
    main()
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["status"] == "loaded"
    assert data["video_id"] == video_id
    assert data["lines_inserted"] == 1
    assert data["zones_inserted"] == 1

    # 2. Test show-geometry CLI command
    out_img = tmp_path / "cli_preview.png"
    monkeypatch.setattr(
        "sys.argv",
        [
            "traffic-vision",
            "show-geometry",
            video_id,
            "--output",
            str(out_img),
            "--frame",
            "0",
            "--config",
            str(cli_cfg),
        ],
    )
    main()
    out_show = capsys.readouterr().out
    show_data = json.loads(out_show)
    assert show_data["video_id"] == video_id
    assert Path(show_data["output_path"]).exists()

    # Verify no processing_run was recorded
    with database_connection(db_path) as conn:
        runs = conn.execute("SELECT count(*) FROM processing_runs").fetchone()[0]
        assert runs == 0
