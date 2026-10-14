import json
import shutil
import subprocess

import cv2
import numpy as np
import pytest

from pattom import prepare
from pattom.runmeta import sha256_file

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _make_vfr(path):
    # Frames at irregular times: 0, 0.033, 0.1, 0.133, ...
    frames = path.parent / "frames"
    frames.mkdir()
    lines = []
    for i in range(20):
        img = np.full((48, 64, 3), i * 10, np.uint8)
        f = frames / f"{i:03d}.png"
        cv2.imwrite(str(f), img)
        lines += [f"file '{f}'", f"duration {0.0333 if i % 2 == 0 else 0.0667}"]
    lst = path.parent / "list.txt"
    lst.write_text("\n".join(lines) + "\n")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-fps_mode", "vfr", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )


@needs_ffmpeg
def test_cfr_copy_leaves_original_untouched(tmp_path):
    src = tmp_path / "orig.mp4"
    _make_vfr(src)
    before = sha256_file(src)
    assert prepare.probe(src).is_vfr
    dst = tmp_path / "cfr" / "copy.mp4"
    meta = prepare.to_cfr(src, dst, 30.0, slot="test")
    assert sha256_file(src) == before
    assert not prepare.probe(dst).is_vfr
    assert meta.parameters["source_sha256"] == before
    assert json.loads(dst.with_suffix(".run.json").read_text())["stage"] == "B.cfr"


def test_refuses_to_overwrite_original(tmp_path):
    src = tmp_path / "a.mp4"
    src.write_bytes(b"x")
    with pytest.raises(ValueError):
        prepare._guard_output(src, src)


def test_refuses_to_write_into_raw(tmp_path):
    with pytest.raises(ValueError):
        prepare._guard_output(tmp_path / "a.mp4", prepare.DATA_RAW / "b.mp4")


def _board_views(n, pattern=(7, 5), sq=40):
    """Render a flat checkerboard through a pinhole camera with known K at random poses."""
    cols, rows = pattern[0] + 1, pattern[1] + 1
    board = np.full(((rows + 2) * sq, (cols + 2) * sq), 255, np.uint8)
    for r in range(rows):
        for c in range(cols):
            if (r + c) % 2 == 0:
                board[(r + 1) * sq:(r + 2) * sq, (c + 1) * sq:(c + 2) * sq] = 0
    h, w = board.shape
    k = np.array([[600.0, 0, 320], [0, 600.0, 240], [0, 0, 1]])
    # board pixels -> board-plane units centred on the board
    to_plane = np.array([[1.0, 0, -w / 2], [0, 1.0, -h / 2], [0, 0, 1]])
    rng = np.random.default_rng(0)
    out = []
    for _ in range(n):
        rvec = rng.uniform(-0.35, 0.35, 3)
        rot, _ = cv2.Rodrigues(rvec)
        t = np.array([rng.uniform(-30, 30), rng.uniform(-30, 30), rng.uniform(750, 950)])
        H = k @ np.column_stack([rot[:, 0], rot[:, 1], t]) @ to_plane
        img = cv2.warpPerspective(board, H / H[2, 2], (640, 480), flags=cv2.INTER_AREA, borderValue=255)
        out.append(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR))
    return out


def test_lens_calibration_on_synthetic_board(tmp_path):
    lens = prepare.calibrate_lens(_board_views(22), (7, 5), 25.0)
    assert lens.frames_used == 22
    assert lens.rms_reprojection_px < 0.5
    assert lens.camera_matrix[0][0] == pytest.approx(600, rel=0.02)
    back = prepare.LensCalibration.load(lens.save(tmp_path / "lens.json"))
    assert back == lens


def test_lens_calibration_needs_enough_frames():
    with pytest.raises(ValueError, match="at least 20"):
        prepare.calibrate_lens(_board_views(5), (7, 5), 25.0)


@needs_ffmpeg
def test_undistort_copy(tmp_path):
    src = tmp_path / "orig.mp4"
    _make_vfr(src)
    cfr = tmp_path / "cfr.mp4"
    prepare.to_cfr(src, cfr, 30.0, slot="test")
    p = prepare.probe(cfr)
    lens = prepare.LensCalibration(
        camera_matrix=[[60.0, 0, 32], [0, 60.0, 24], [0, 0, 1]],
        dist_coeffs=[-0.1, 0, 0, 0, 0],
        image_size=(p.width, p.height),
        rms_reprojection_px=0.1,
        frames_used=20,
        pattern_inner_corners=(7, 5),
        square_size_mm=25.0,
        source_video="synthetic",
        source_sha256="",
    )
    dst = tmp_path / "und.mp4"
    meta = prepare.undistort_video(cfr, dst, lens, slot="test")
    assert meta.parameters["frames"] == p.n_frames
    assert (prepare.probe(dst).width, prepare.probe(dst).height) == lens.image_size


@needs_ffmpeg
def test_undistort_refuses_vfr(tmp_path):
    src = tmp_path / "orig.mp4"
    _make_vfr(src)
    lens = prepare.LensCalibration([[60.0, 0, 32], [0, 60.0, 24], [0, 0, 1]], [0, 0, 0, 0, 0],
                                   (64, 48), 0.1, 20, (7, 5), 25.0, "", "")
    with pytest.raises(ValueError, match="variable frame rate"):
        prepare.undistort_video(src, tmp_path / "x.mp4", lens, slot="test")
