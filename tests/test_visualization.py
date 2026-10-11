"""Tests for Phase 04 visualization, rendering overlays, and service orchestration.

Software fixture notice: Test fixtures are synthetic software fixtures for validating
invariants and error handling; they do not represent real-world CCTV footage validation.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
from uuid import uuid4

import cv2
import numpy as np
import pytest

from backend.config import load_config
from backend.database.connection import bootstrap_database, database_connection
from backend.database.repository import (
    insert_run,
    insert_tracks,
    insert_video,
)
from backend.media import inspect_video, sha256_file
from backend.services.visualization import (
    build_run_trajectories,
    render_preview_visualization,
    render_video_visualization,
)
from backend.trajectories import Trajectory, TrajectoryPoint, build_trajectories
from backend.visualization import (
    VisualizationConfig,
    get_track_color,
    render_frame_annotations,
)


@pytest.fixture
def synthetic_video(tmp_path: Path) -> Path:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is required for the synthetic media fixture")
    video_path = tmp_path / "synthetic_vis.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x120:r=10:d=1",
            "-pix_fmt",
            "yuv420p",
            str(video_path),
        ],
        check=True,
        capture_output=True,
    )
    return video_path


def test_visualization_config_defaults_and_overrides() -> None:
    cfg = VisualizationConfig.from_dict(None)
    assert cfg.show_boxes is True
    assert cfg.show_labels is True
    assert cfg.show_trails is True
    assert cfg.trail_length == 30

    custom = VisualizationConfig.from_dict(
        {
            "show_boxes": False,
            "show_labels": True,
            "show_trails": False,
            "trail_length": 15,
        }
    )
    assert custom.show_boxes is False
    assert custom.show_trails is False
    assert custom.trail_length == 15


def test_get_track_color_deterministic() -> None:
    c1 = get_track_color(7)
    c2 = get_track_color(7)
    assert c1 == c2
    assert isinstance(c1, tuple) and len(c1) == 3


def test_render_frame_annotations_deterministic_output() -> None:
    img = np.zeros((120, 160, 3), dtype=np.uint8)
    point1 = TrajectoryPoint(
        frame_number=1,
        timestamp_s=0.1,
        ground_x=30.0,
        ground_y=60.0,
        x1=10.0,
        y1=20.0,
        x2=50.0,
        y2=60.0,
        confidence=0.88,
        vehicle_class="car",
    )
    traj1 = Trajectory(
        run_id="run-1",
        video_id="vid-1",
        track_id=1,
        points=[point1],
        consensus_class="car",
        status="complete",
        status_reason="normal",
        total_observations=1,
        missing_frames_count=0,
        duration_s=0.0,
        is_incomplete=False,
    )

    out1 = render_frame_annotations(img, 1, [(traj1, point1)])
    out2 = render_frame_annotations(img, 1, [(traj1, point1)])
    assert np.array_equal(out1, out2)


def test_render_frame_annotations_toggles() -> None:
    img = np.zeros((120, 160, 3), dtype=np.uint8)
    p1 = TrajectoryPoint(
        frame_number=1,
        timestamp_s=0.1,
        ground_x=30.0,
        ground_y=60.0,
        x1=10.0,
        y1=20.0,
        x2=50.0,
        y2=60.0,
        confidence=0.88,
        vehicle_class="car",
    )
    p2 = TrajectoryPoint(
        frame_number=2,
        timestamp_s=0.2,
        ground_x=35.0,
        ground_y=65.0,
        x1=15.0,
        y1=25.0,
        x2=55.0,
        y2=65.0,
        confidence=0.90,
        vehicle_class="car",
    )
    traj = Trajectory(
        run_id="run-1",
        video_id="vid-1",
        track_id=1,
        points=[p1, p2],
        consensus_class="car",
        status="complete",
        status_reason="normal",
        total_observations=2,
        missing_frames_count=0,
        duration_s=0.1,
        is_incomplete=False,
    )

    full_render = render_frame_annotations(
        img, 2, [(traj, p2)], VisualizationConfig(show_boxes=True, show_labels=True, show_trails=True)
    )
    no_boxes = render_frame_annotations(
        img, 2, [(traj, p2)], VisualizationConfig(show_boxes=False, show_labels=True, show_trails=True)
    )
    no_labels = render_frame_annotations(
        img, 2, [(traj, p2)], VisualizationConfig(show_boxes=True, show_labels=False, show_trails=True)
    )
    no_trails = render_frame_annotations(
        img, 2, [(traj, p2)], VisualizationConfig(show_boxes=True, show_labels=True, show_trails=False)
    )

    assert not np.array_equal(full_render, no_boxes)
    assert not np.array_equal(full_render, no_labels)
    assert not np.array_equal(full_render, no_trails)


def test_render_frame_annotations_empty_tracks_returns_clean_copy() -> None:
    img = np.ones((50, 50, 3), dtype=np.uint8) * 128
    out = render_frame_annotations(img, 1, [])
    assert np.array_equal(img, out)
    # Ensure it is a copy, not the same object
    assert out is not img


def test_render_frame_annotations_handles_out_of_bounds_and_invalid_boxes() -> None:
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    # Malformed box x1 > x2
    p_invalid = TrajectoryPoint(
        frame_number=1,
        timestamp_s=0.1,
        ground_x=50.0,
        ground_y=50.0,
        x1=60.0,
        y1=10.0,
        x2=20.0,
        y2=50.0,
        confidence=0.5,
        vehicle_class="car",
    )
    traj = Trajectory(
        run_id="run-1",
        video_id="vid-1",
        track_id=1,
        points=[p_invalid],
        consensus_class="car",
        status="invalid",
        status_reason="malformed",
        total_observations=1,
        missing_frames_count=0,
        duration_s=0.0,
        is_incomplete=True,
    )
    # Should safely ignore malformed box without throwing exception
    out = render_frame_annotations(img, 1, [(traj, p_invalid)])
    assert out.shape == img.shape


def test_build_run_trajectories_service(tmp_path: Path) -> None:
    db_path = tmp_path / "test.sqlite3"
    bootstrap_database(db_path)

    with database_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO videos (video_id, filename, path, sha256, fps_nominal, width, height, duration_s, frame_count, ingested_at)
            VALUES ('vid-1', 'test.mp4', 'dummy.mp4', 'sha123', 30.0, 1280, 720, 5.0, 150, '2026-10-11T00:00:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO processing_runs (run_id, video_id, config_hash, config_json, schema_version, code_version, source_video_sha256, started_at, status)
            VALUES ('track-run-1', 'vid-1', 'cfg1', '{}', '1.0.0', 'sha', 'sha123', '2026-10-11T00:00:00Z', 'completed')
            """
        )
        insert_tracks(
            conn,
            [
                {
                    "track_observation_id": "obs-1",
                    "run_id": "track-run-1",
                    "video_id": "vid-1",
                    "track_id": 10,
                    "frame_number": 0,
                    "timestamp_s": 0.0,
                    "vehicle_class": "bus",
                    "confidence": 0.9,
                    "x1": 100,
                    "y1": 100,
                    "x2": 200,
                    "y2": 300,
                    "ground_x": 150,
                    "ground_y": 300,
                    "world_x": None,
                    "world_y": None,
                    "calibration_id": None,
                    "trajectory_status": "complete",
                },
                {
                    "track_observation_id": "obs-2",
                    "run_id": "track-run-1",
                    "video_id": "vid-1",
                    "track_id": 10,
                    "frame_number": 1,
                    "timestamp_s": 0.033,
                    "vehicle_class": "bus",
                    "confidence": 0.92,
                    "x1": 105,
                    "y1": 100,
                    "x2": 205,
                    "y2": 300,
                    "ground_x": 155,
                    "ground_y": 300,
                    "world_x": None,
                    "world_y": None,
                    "calibration_id": None,
                    "trajectory_status": "complete",
                },
            ],
        )

        trajectories = build_run_trajectories(conn, "track-run-1")

    assert len(trajectories) == 1
    assert 10 in trajectories
    traj = trajectories[10]
    assert traj.consensus_class == "bus"
    assert len(traj.points) == 2


def test_render_preview_visualization_creates_image(tmp_path: Path, synthetic_video: Path) -> None:
    db_path = tmp_path / "traffic.sqlite3"
    bootstrap_database(db_path)
    video_meta = inspect_video(synthetic_video)
    video_sha = sha256_file(synthetic_video)

    with database_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO videos (video_id, filename, path, sha256, fps_nominal, width, height, duration_s, frame_count, ingested_at)
            VALUES ('vid-syn', 'syn.mp4', ?, ?, ?, ?, ?, ?, ?, '2026-10-11T00:00:00Z')
            """,
            (
                str(synthetic_video),
                video_sha,
                video_meta.fps_nominal,
                video_meta.width,
                video_meta.height,
                video_meta.duration_s,
                video_meta.frame_count,
            ),
        )
        conn.execute(
            """
            INSERT INTO processing_runs (run_id, video_id, config_hash, config_json, schema_version, code_version, source_video_sha256, started_at, status)
            VALUES ('track-run-syn', 'vid-syn', 'cfg1', '{}', '1.0.0', 'code1', ?, '2026-10-11T00:00:00Z', 'completed')
            """,
            (video_sha,),
        )
        insert_tracks(
            conn,
            [
                {
                    "track_observation_id": "obs-syn-1",
                    "run_id": "track-run-syn",
                    "video_id": "vid-syn",
                    "track_id": 1,
                    "frame_number": 2,
                    "timestamp_s": 0.2,
                    "vehicle_class": "car",
                    "confidence": 0.85,
                    "x1": 20,
                    "y1": 20,
                    "x2": 60,
                    "y2": 60,
                    "ground_x": 40,
                    "ground_y": 60,
                    "world_x": None,
                    "world_y": None,
                    "calibration_id": None,
                    "trajectory_status": "complete",
                }
            ],
        )

    config = load_config(overrides={"paths": {"database_path": str(db_path)}})
    out_img_path = tmp_path / "preview.jpg"
    rendered_path = render_preview_visualization(
        "track-run-syn",
        2,
        config,
        repository_root=tmp_path,
        output_path=out_img_path,
    )

    assert rendered_path.is_file()
    loaded = cv2.imread(str(rendered_path))
    assert loaded is not None
    assert loaded.shape[0] == video_meta.height
    assert loaded.shape[1] == video_meta.width


def test_render_video_visualization_lineage_and_provenance(tmp_path: Path, synthetic_video: Path) -> None:
    db_path = tmp_path / "traffic.sqlite3"
    bootstrap_database(db_path)
    video_meta = inspect_video(synthetic_video)
    video_sha = sha256_file(synthetic_video)

    with database_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO videos (video_id, filename, path, sha256, fps_nominal, width, height, duration_s, frame_count, ingested_at)
            VALUES ('vid-syn', 'syn.mp4', ?, ?, ?, ?, ?, ?, ?, '2026-10-11T00:00:00Z')
            """,
            (
                str(synthetic_video),
                video_sha,
                video_meta.fps_nominal,
                video_meta.width,
                video_meta.height,
                video_meta.duration_s,
                video_meta.frame_count,
            ),
        )
        conn.execute(
            """
            INSERT INTO processing_runs (run_id, video_id, config_hash, config_json, schema_version, code_version, source_video_sha256, started_at, status)
            VALUES ('track-run-syn', 'vid-syn', 'cfg1', '{}', '1.0.0', 'code1', ?, '2026-10-11T00:00:00Z', 'completed')
            """,
            (video_sha,),
        )
        insert_tracks(
            conn,
            [
                {
                    "track_observation_id": "obs-syn-1",
                    "run_id": "track-run-syn",
                    "video_id": "vid-syn",
                    "track_id": 1,
                    "frame_number": 0,
                    "timestamp_s": 0.0,
                    "vehicle_class": "car",
                    "confidence": 0.85,
                    "x1": 20,
                    "y1": 20,
                    "x2": 60,
                    "y2": 60,
                    "ground_x": 40,
                    "ground_y": 60,
                    "world_x": None,
                    "world_y": None,
                    "calibration_id": None,
                    "trajectory_status": "complete",
                }
            ],
        )

    out_video_path = tmp_path / "out_vis.mp4"
    config = load_config(overrides={"paths": {"database_path": str(db_path)}})
    vis_run_id = render_video_visualization(
        "track-run-syn",
        config,
        repository_root=tmp_path,
        output_path=out_video_path,
    )

    assert out_video_path.is_file()
    assert out_video_path.stat().st_size > 0

    with database_connection(db_path) as conn:
        run = conn.execute("SELECT parent_run_id, status, notes FROM processing_runs WHERE run_id = ?", (vis_run_id,)).fetchone()
        assert run["parent_run_id"] == "track-run-syn"
        assert run["status"] == "completed"
        notes = json.loads(run["notes"])
        assert notes["output_path"] == str(out_video_path)
        assert notes["rendered_frames"] == 10  # 1s at 10fps


def test_render_video_visualization_rejects_missing_or_incomplete_parent(tmp_path: Path) -> None:
    db_path = tmp_path / "traffic.sqlite3"
    bootstrap_database(db_path)
    config = load_config(overrides={"paths": {"database_path": str(db_path)}})

    with pytest.raises(ValueError, match="does not exist"):
        render_video_visualization("nonexistent-run", config, tmp_path)

    with database_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO videos (video_id, filename, path, sha256, ingested_at)
            VALUES ('vid-1', 'v.mp4', 'dummy.mp4', 'sha', '2026-10-11T00:00:00Z')
            """
        )
        conn.execute(
            """
            INSERT INTO processing_runs (run_id, video_id, config_hash, config_json, schema_version, code_version, source_video_sha256, started_at, status)
            VALUES ('running-parent', 'vid-1', 'cfg', '{}', '1.0.0', 'c', 'sha', '2026-10-11T00:00:00Z', 'running')
            """
        )

    with pytest.raises(ValueError, match="not completed"):
        render_video_visualization("running-parent", config, tmp_path)


def test_render_video_visualization_interruption_cleanup(tmp_path: Path, synthetic_video: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "traffic.sqlite3"
    bootstrap_database(db_path)
    video_meta = inspect_video(synthetic_video)
    video_sha = sha256_file(synthetic_video)

    with database_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO videos (video_id, filename, path, sha256, fps_nominal, width, height, duration_s, frame_count, ingested_at)
            VALUES ('vid-syn', 'syn.mp4', ?, ?, ?, ?, ?, ?, ?, '2026-10-11T00:00:00Z')
            """,
            (
                str(synthetic_video),
                video_sha,
                video_meta.fps_nominal,
                video_meta.width,
                video_meta.height,
                video_meta.duration_s,
                video_meta.frame_count,
            ),
        )
        conn.execute(
            """
            INSERT INTO processing_runs (run_id, video_id, config_hash, config_json, schema_version, code_version, source_video_sha256, started_at, status)
            VALUES ('track-run-syn', 'vid-syn', 'cfg1', '{}', '1.0.0', 'code1', ?, '2026-10-11T00:00:00Z', 'completed')
            """,
            (video_sha,),
        )

    # Monkeypatch iter_decoded_images to simulate a crash during rendering
    def faulty_iter_decoded_images(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Simulated crash mid-stream")

    monkeypatch.setattr("backend.services.visualization.iter_decoded_images", faulty_iter_decoded_images)

    out_video_path = tmp_path / "interrupted.mp4"
    config = load_config(overrides={"paths": {"database_path": str(db_path)}})

    with pytest.raises(RuntimeError, match="Simulated crash"):
        render_video_visualization(
            "track-run-syn",
            config,
            repository_root=tmp_path,
            output_path=out_video_path,
        )

    # Temporary file must be cleaned up
    temp_file = out_video_path.with_name(f"{out_video_path.stem}.tmp{out_video_path.suffix}")
    assert not temp_file.is_file()
    assert not out_video_path.is_file()

    # Database run status must be recorded as failed
    with database_connection(db_path) as conn:
        failed_run = conn.execute("SELECT status, notes FROM processing_runs WHERE parent_run_id = 'track-run-syn'").fetchone()
        assert failed_run is not None
        assert failed_run["status"] == "failed"
        assert "Simulated crash" in failed_run["notes"]


def test_render_video_visualization_zero_frames_fails(tmp_path: Path, synthetic_video: Path) -> None:
    db_path = tmp_path / "traffic_zero.sqlite3"
    bootstrap_database(db_path)
    video_meta = inspect_video(synthetic_video)
    video_sha = sha256_file(synthetic_video)

    with database_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO videos (video_id, filename, path, sha256, fps_nominal, width, height, duration_s, frame_count, ingested_at)
            VALUES ('vid-syn2', 'syn2.mp4', ?, ?, ?, ?, ?, ?, ?, '2026-10-11T00:00:00Z')
            """,
            (
                str(synthetic_video),
                video_sha,
                video_meta.fps_nominal,
                video_meta.width,
                video_meta.height,
                video_meta.duration_s,
                video_meta.frame_count,
            ),
        )
        conn.execute(
            """
            INSERT INTO processing_runs (run_id, video_id, config_hash, config_json, schema_version, code_version, source_video_sha256, started_at, status)
            VALUES ('track-run-zero', 'vid-syn2', 'cfg1', '{}', '1.0.0', 'code1', ?, '2026-10-11T00:00:00Z', 'completed')
            """,
            (video_sha,),
        )

    out_video_path = tmp_path / "zero_out.mp4"
    config = load_config(overrides={"paths": {"database_path": str(db_path)}})

    # Frame 999 is past the synthetic video duration (10 frames)
    with pytest.raises(RuntimeError, match="No frames rendered"):
        render_video_visualization(
            "track-run-zero",
            config,
            repository_root=tmp_path,
            output_path=out_video_path,
            start_frame=999,
            end_frame=1000,
        )

    # Verify no file was produced and run marked failed
    assert not out_video_path.is_file()
    temp_file = out_video_path.with_name(f"{out_video_path.stem}.tmp{out_video_path.suffix}")
    assert not temp_file.is_file()

    with database_connection(db_path) as conn:
        failed_run = conn.execute("SELECT status, notes FROM processing_runs WHERE parent_run_id = 'track-run-zero'").fetchone()
        assert failed_run is not None
        assert failed_run["status"] == "failed"
        assert "No frames rendered" in failed_run["notes"]


def test_cli_visualize_argument_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.cli import main

    monkeypatch.setattr("sys.argv", ["traffic-cli", "visualize", "run-1", "--preview-frame", "-1"])
    with pytest.raises(SystemExit, match="preview-frame must be >= 0"):
        main()

    monkeypatch.setattr("sys.argv", ["traffic-cli", "visualize", "run-1", "--start-frame", "-5"])
    with pytest.raises(SystemExit, match="start-frame must be >= 0"):
        main()

    monkeypatch.setattr("sys.argv", ["traffic-cli", "visualize", "run-1", "--start-frame", "50", "--end-frame", "10"])
    with pytest.raises(SystemExit, match="cannot be greater than end-frame"):
        main()
