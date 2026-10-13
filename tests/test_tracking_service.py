from pathlib import Path
import shutil
import sqlite3
import subprocess
from unittest.mock import patch

import numpy as np
import pytest

from backend.config import load_config
from backend.detection import RawDetection
from backend.services.detection import run_detection
from backend.services.ingestion import ingest_video
from backend.services.tracking import run_tracking
from backend.tracking import ByteTrackerAdapter


class FakeDetector:
    def predict(self, image: np.ndarray, *, confidence: float, iou: float, image_size: int) -> list[RawDetection]:
        # Return a moving car box
        return [RawDetection(2, "car", 0.9, 2, 3, 12, 13)]


@pytest.fixture
def source_video(tmp_path: Path) -> Path:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is required for the synthetic media fixture")
    path = tmp_path / "source.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=32x24:r=2:d=2", "-pix_fmt", "yuv420p", str(path)],
        check=True,
        capture_output=True,
    )
    return path


def test_tracking_run_persists_canonical_tracks(tmp_path: Path, source_video: Path) -> None:
    database = tmp_path / "traffic.sqlite3"
    model_path = tmp_path / "fake-weights.pt"
    model_path.write_bytes(b"fixture-weights")

    config = load_config(
        overrides={
            "paths": {"database_path": str(database)},
            "detection": {
                "model": {"version": "fixture-v1", "path": str(model_path), "device": "cpu"},
                "class_mapping": {"car": "car"},
            },
            "tracking": {
                "tracker_type": "bytetrack",
                "track_high_thresh": 0.5,
                "track_low_thresh": 0.1,
                "new_track_thresh": 0.6,
                "match_thresh": 0.8,
                "track_buffer_seconds": 1.0,
            },
        }
    )

    # 1. Ingest (Phase 01)
    ingest_result = ingest_video(source_video, config, repository_root=Path.cwd())
    ingest_run_id = ingest_result["run_id"]

    # 2. Detect (Phase 02)
    detection_run_id = run_detection(ingest_run_id, config, Path.cwd(), FakeDetector())

    # 3. Track (Phase 03)
    tracking_run_id = run_tracking(detection_run_id, config, Path.cwd())

    # 4. Verify SQLite persistence and contracts
    with sqlite3.connect(database) as connection:
        run = connection.execute(
            "SELECT parent_run_id, model_version, status, notes FROM processing_runs WHERE run_id = ?",
            (tracking_run_id,),
        ).fetchone()

        track_rows = connection.execute(
            """
            SELECT run_id, video_id, track_id, frame_number, vehicle_class,
                   confidence, ground_x, ground_y, world_x, world_y, calibration_id, trajectory_status
            FROM tracks
            WHERE run_id = ?
            ORDER BY frame_number ASC
            """,
            (tracking_run_id,),
        ).fetchall()

    assert run is not None
    assert run[0] == detection_run_id
    assert run[1] == "fixture-v1"
    assert run[2] == "completed"
    assert "Phase 03 ByteTrack run completed" in run[3]
    assert "id_switches=unmeasured" in run[3]

    assert len(track_rows) > 0
    for row in track_rows:
        assert row[0] == tracking_run_id
        assert row[1] == ingest_result["video_id"]
        assert row[4] == "car"
        assert row[5] == pytest.approx(0.9, rel=1e-2)
        assert row[6] == 7.0  # (2 + 12) / 2
        assert row[7] == 13.0  # y2
        assert row[8] is None  # world_x MUST be NULL in Phase 03
        assert row[9] is None  # world_y MUST be NULL in Phase 03
        assert row[10] is None  # calibration_id MUST be NULL in Phase 03
        assert row[11] == "complete"


def test_tracking_bounded_memory_batch_persistence(tmp_path: Path, source_video: Path) -> None:
    database = tmp_path / "traffic_batch.sqlite3"
    model_path = tmp_path / "fake-weights.pt"
    model_path.write_bytes(b"fixture-weights")

    # Set batch_size = 1 so every observation triggers a separate batch flush
    config = load_config(
        overrides={
            "paths": {"database_path": str(database)},
            "streaming": {"frame_batch_size": 1},
            "detection": {
                "model": {"version": "fixture-v1", "path": str(model_path), "device": "cpu"},
                "class_mapping": {"car": "car"},
            },
            "tracking": {"batch_size": 1},
        }
    )

    ingest_result = ingest_video(source_video, config, repository_root=Path.cwd())
    detection_run_id = run_detection(ingest_result["run_id"], config, Path.cwd(), FakeDetector())
    tracking_run_id = run_tracking(detection_run_id, config, Path.cwd())

    with sqlite3.connect(database) as connection:
        run = connection.execute(
            "SELECT status FROM processing_runs WHERE run_id = ?",
            (tracking_run_id,),
        ).fetchone()
        count = connection.execute(
            "SELECT COUNT(*) FROM tracks WHERE run_id = ?",
            (tracking_run_id,),
        ).fetchone()[0]

    assert run[0] == "completed"
    assert count >= 2


def test_tracking_atomic_rollback_on_database_failure(tmp_path: Path, source_video: Path) -> None:
    database = tmp_path / "traffic_fail.sqlite3"
    model_path = tmp_path / "fake-weights.pt"
    model_path.write_bytes(b"fixture-weights")

    config = load_config(
        overrides={
            "paths": {"database_path": str(database)},
            "detection": {
                "model": {"version": "fixture-v1", "path": str(model_path), "device": "cpu"},
                "class_mapping": {"car": "car"},
            },
            "tracking": {"batch_size": 1},
        }
    )

    ingest_result = ingest_video(source_video, config, repository_root=Path.cwd())
    detection_run_id = run_detection(ingest_result["run_id"], config, Path.cwd(), FakeDetector())

    # Simulate an error on the second batch insertion
    real_insert = __import__("backend.database.repository", fromlist=["insert_tracks"]).insert_tracks
    call_count = 0

    def mock_insert_tracks(connection, rows):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise sqlite3.OperationalError("Simulated database failure during batch 2")
        return real_insert(connection, rows)

    with patch("backend.services.tracking.insert_tracks", side_effect=mock_insert_tracks):
        with pytest.raises(sqlite3.OperationalError, match="Simulated database failure"):
            run_tracking(detection_run_id, config, Path.cwd())

    # Verify atomic rollback: run status is 'failed', tracks table has 0 rows
    with sqlite3.connect(database) as connection:
        runs = connection.execute(
            "SELECT status, notes FROM processing_runs WHERE parent_run_id = ?",
            (detection_run_id,),
        ).fetchall()
        tracks_count = connection.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]

    assert len(runs) == 1
    assert runs[0][0] == "failed"
    assert "Simulated database failure" in runs[0][1]
    assert tracks_count == 0  # Atomic rollback cleaned up batch 1!


def test_tracking_rejects_missing_or_incomplete_parent_run(tmp_path: Path) -> None:
    database = tmp_path / "traffic.sqlite3"
    config = load_config(overrides={"paths": {"database_path": str(database)}})

    from backend.database.connection import bootstrap_database

    bootstrap_database(database)

    with pytest.raises(ValueError, match="Parent processing run does not exist"):
        run_tracking("non-existent-parent", config, Path.cwd())


def test_tracking_windowed_chunk_streaming(tmp_path: Path, source_video: Path) -> None:
    """Verify that tracking streams in bounded chunks, correctly traversing chunk boundaries."""
    database = tmp_path / "traffic_chunks.sqlite3"
    model_path = tmp_path / "fake-weights.pt"
    model_path.write_bytes(b"fixture-weights")

    config = load_config(
        overrides={
            "paths": {"database_path": str(database)},
            "streaming": {"frame_batch_size": 2},
            "detection": {
                "model": {"version": "fixture-v1", "path": str(model_path), "device": "cpu"},
                "class_mapping": {"car": "car"},
            },
            "tracking": {"batch_size": 2},
        }
    )

    ingest_result = ingest_video(source_video, config, repository_root=Path.cwd())
    detection_run_id = run_detection(ingest_result["run_id"], config, Path.cwd(), FakeDetector())
    tracking_run_id = run_tracking(detection_run_id, config, Path.cwd())

    with sqlite3.connect(database) as conn:
        run = conn.execute("SELECT status FROM processing_runs WHERE run_id = ?", (tracking_run_id,)).fetchone()
        tracks = conn.execute("SELECT COUNT(*) FROM tracks WHERE run_id = ?", (tracking_run_id,)).fetchone()[0]

    assert run[0] == "completed"
    assert tracks >= 2


def test_tracking_multichunk_boundary_consistency(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """T1: Verify streaming across chunk boundaries with chunk_frames=3 on >=12 frame video."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is required for the synthetic media fixture")

    # Create video of 15 frames (r=5, d=3) -> 5 chunks of 3 frames
    long_video = tmp_path / "long_video.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=32x24:r=5:d=3", "-pix_fmt", "yuv420p", str(long_video)],
        check=True,
        capture_output=True,
    )

    database_chunks = tmp_path / "traffic_chunks_3.sqlite3"
    database_default = tmp_path / "traffic_default_500.sqlite3"
    model_path = tmp_path / "fake-weights.pt"
    model_path.write_bytes(b"fixture-weights")

    cfg_chunks = load_config(
        overrides={
            "paths": {"database_path": str(database_chunks)},
            "streaming": {"frame_batch_size": 3},
            "detection": {
                "model": {"version": "fixture-v1", "path": str(model_path), "device": "cpu"},
                "class_mapping": {"car": "car"},
            },
            "tracking": {"chunk_frames": 3, "batch_size": 3},
        }
    )
    cfg_default = load_config(
        overrides={
            "paths": {"database_path": str(database_default)},
            "streaming": {"frame_batch_size": 3},
            "detection": {
                "model": {"version": "fixture-v1", "path": str(model_path), "device": "cpu"},
                "class_mapping": {"car": "car"},
            },
            "tracking": {"chunk_frames": 500, "batch_size": 3},
        }
    )

    ingest_res_chunks = ingest_video(long_video, cfg_chunks, repository_root=tmp_path)
    det_run_chunks = run_detection(ingest_res_chunks["run_id"], cfg_chunks, tmp_path, FakeDetector())

    ingest_res_default = ingest_video(long_video, cfg_default, repository_root=tmp_path)
    det_run_default = run_detection(ingest_res_default["run_id"], cfg_default, tmp_path, FakeDetector())

    import logging
    with caplog.at_level(logging.INFO):
        caplog.clear()
        track_run_chunks = run_tracking(det_run_chunks, cfg_chunks, tmp_path)

    # (c) assert the chunk loop ran more than once (check log call)
    chunk_logs = [rec.message for rec in caplog.records if "Processing tracking chunk frames" in rec.message]
    assert len(chunk_logs) >= 4, f"Expected at least 4 chunk log calls, got {len(chunk_logs)}: {chunk_logs}"

    track_run_default = run_tracking(det_run_default, cfg_default, tmp_path)

    with sqlite3.connect(database_chunks) as conn:
        rows_chunks = conn.execute(
            "SELECT track_id, frame_number, vehicle_class, confidence, x1, y1, x2, y2, ground_x, ground_y "
            "FROM tracks WHERE run_id = ? ORDER BY frame_number ASC",
            (track_run_chunks,),
        ).fetchall()

    with sqlite3.connect(database_default) as conn:
        rows_default = conn.execute(
            "SELECT track_id, frame_number, vehicle_class, confidence, x1, y1, x2, y2, ground_x, ground_y "
            "FROM tracks WHERE run_id = ? ORDER BY frame_number ASC",
            (track_run_default,),
        ).fetchall()

    # (a) Assert persisted track observations and track IDs are identical
    assert len(rows_chunks) >= 12
    assert rows_chunks == rows_default

    # (b) Assert the same track ID continues across every boundary
    first_track_id = rows_chunks[0][0]
    for row in rows_chunks:
        assert row[0] == first_track_id, f"Track ID switched from {first_track_id} to {row[0]} at frame {row[1]}"

