from pathlib import Path
import shutil
import sqlite3
import subprocess

import numpy as np
import pytest

from backend.config import load_config
from backend.detection import RawDetection
from backend.services.detection import run_detection
from backend.services.ingestion import ingest_video


class FakeDetector:
    def predict(self, image: np.ndarray, *, confidence: float, iou: float, image_size: int) -> list[RawDetection]:
        assert image_size == 640
        return [RawDetection(2, "car", 0.9, 2, 3, 12, 13)]


@pytest.fixture
def source_video(tmp_path: Path) -> Path:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is required for the synthetic media fixture")
    path = tmp_path / "source.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=32x24:r=2:d=1", "-pix_fmt", "yuv420p", str(path)],
        check=True,
        capture_output=True,
    )
    return path


def test_detection_run_persists_only_canonical_detections(tmp_path: Path, source_video: Path) -> None:
    database = tmp_path / "traffic.sqlite3"
    model_path = tmp_path / "fake-weights.pt"
    model_path.write_bytes(b"fixture-weights")
    config = load_config(
        overrides={
            "paths": {"database_path": str(database)},
            "detection": {"model": {"version": "fixture-v1", "path": str(model_path), "device": "cpu"}, "class_mapping": {"car": "car"}},
        }
    )
    parent = ingest_video(source_video, config, repository_root=Path.cwd())
    detection_run_id = run_detection(parent["run_id"], config, Path.cwd(), FakeDetector())

    with sqlite3.connect(database) as connection:
        run = connection.execute("SELECT parent_run_id, model_version, status FROM processing_runs WHERE run_id = ?", (detection_run_id,)).fetchone()
        rows = connection.execute("SELECT run_id, class_name, ground_x, ground_y, frame_number FROM detections ORDER BY frame_number").fetchall()
        tracks = connection.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]

    assert run == (parent["run_id"], "fixture-v1", "completed")
    assert len(rows) == 2
    assert all(row[0] == detection_run_id and row[1] == "car" for row in rows)
    assert rows[0][2:4] == (7.0, 13.0)
    assert tracks == 0
