from pathlib import Path
import shutil
import sqlite3
import subprocess

import pytest

from backend.config import load_config
from backend.media import preview_frame
from backend.services.ingestion import ingest_video


@pytest.fixture
def fixture_video(tmp_path: Path) -> Path:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is required for the synthetic media fixture")
    video_path = tmp_path / "fixture.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=32x24:r=5:d=1",
            "-pix_fmt",
            "yuv420p",
            str(video_path),
        ],
        check=True,
        capture_output=True,
    )
    return video_path


def test_ingestion_persists_metadata_run_and_decoder_pts(tmp_path: Path, fixture_video: Path) -> None:
    database_path = tmp_path / "traffic.sqlite3"
    config = load_config(overrides={"paths": {"database_path": str(database_path)}, "streaming": {"frame_batch_size": 2}})
    result = ingest_video(fixture_video, config, repository_root=Path.cwd())

    with sqlite3.connect(database_path) as connection:
        video = connection.execute("SELECT width, height, frame_count, sha256 FROM videos").fetchone()
        run = connection.execute("SELECT status, config_hash, code_version FROM processing_runs").fetchone()
        timestamps = connection.execute("SELECT frame_number, pts_s FROM video_frames ORDER BY frame_number").fetchall()

    assert result["timestamp_audit"]["timestamp_quality"] == "continuous"
    assert video[:3] == (32, 24, 5)
    assert len(video[3]) == 64
    assert run[0] == "completed"
    assert len(run[1]) == 64
    assert len(run[2]) == 40
    assert len(timestamps) == 5
    assert timestamps[0][1] == pytest.approx(0.0)
    assert timestamps[-1][1] > timestamps[0][1]


def test_preview_decodes_one_requested_frame_sequentially(fixture_video: Path) -> None:
    preview = preview_frame(fixture_video, 3)
    assert preview.frame_number == 3
    assert preview.width == 32
    assert preview.height == 24
    assert preview.pts_s > 0
