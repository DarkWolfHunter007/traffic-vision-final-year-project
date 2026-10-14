"""Stage B: preparation (ARCHITECTURE section 3, FR-03, PLAN P2).

Originals are never modified. Every step writes a new file and a run-metadata
record next to it, and checks the original's SHA-256 before and after.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np

from pattom.paths import DATA_RAW
from pattom.runmeta import RunMetadata, sha256_file

MIN_CHECKERBOARD_FRAMES = 20  # PLAN P1 exit gate


def _require(tool: str) -> str:
    path = shutil.which(tool)
    if path is None:
        raise RuntimeError(f"{tool} is not installed or not on PATH")
    return path


def _guard_output(src: Path, dst: Path) -> None:
    src, dst = src.resolve(), dst.resolve()
    if dst == src:
        raise ValueError("output would overwrite the original")
    if DATA_RAW.resolve() in dst.parents:
        raise ValueError(f"{DATA_RAW} holds originals only; write copies elsewhere")


def _rate(text: str) -> float:
    num, _, den = text.partition("/")
    return float(num) / float(den or 1) if float(den or 1) else 0.0


@dataclass
class VideoProbe:
    path: str
    width: int
    height: int
    codec: str
    r_frame_rate: float
    avg_frame_rate: float
    n_frames: int
    duration_s: float
    min_frame_interval_s: float
    max_frame_interval_s: float
    is_vfr: bool


def probe(path: Path, vfr_tolerance: float = 0.05) -> VideoProbe:
    """Read stream info and per-frame timestamps; flag variable frame rate.

    The file is treated as VFR when any frame interval differs from the
    nominal interval by more than vfr_tolerance (fraction).
    """
    ffprobe = _require("ffprobe")
    info = json.loads(
        subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_streams", "-of", "json", str(path)],
            capture_output=True, text=True, check=True,
        ).stdout
    )["streams"][0]
    pts = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "packet=pts_time",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    times = np.sort(np.array([float(t) for t in pts if t not in ("", "N/A")]))
    if times.size < 2:
        raise ValueError(f"{path}: fewer than two timestamped frames")
    dt = np.diff(times)
    r_rate = _rate(info["r_frame_rate"])
    nominal = 1.0 / r_rate if r_rate else float(np.median(dt))
    is_vfr = bool(np.any(np.abs(dt - nominal) > vfr_tolerance * nominal))
    return VideoProbe(
        path=str(path),
        width=int(info["width"]),
        height=int(info["height"]),
        codec=info.get("codec_name", ""),
        r_frame_rate=r_rate,
        avg_frame_rate=_rate(info.get("avg_frame_rate", "0/1")),
        n_frames=int(times.size),
        duration_s=float(times[-1] - times[0] + nominal),
        min_frame_interval_s=float(dt.min()),
        max_frame_interval_s=float(dt.max()),
        is_vfr=is_vfr,
    )


def to_cfr(src: Path, dst: Path, fps: float, slot: str, crf: int = 18) -> RunMetadata:
    """Write a constant-frame-rate copy of src (FR-03). Audio is dropped."""
    _guard_output(src, dst)
    ffmpeg = _require("ffmpeg")
    before = sha256_file(src)
    src_probe = probe(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [ffmpeg, "-v", "error", "-y", "-i", str(src), "-fps_mode", "cfr", "-r", str(fps),
         "-c:v", "libx264", "-crf", str(crf), "-preset", "medium", "-pix_fmt", "yuv420p", "-an", str(dst)],
        check=True,
    )
    if sha256_file(src) != before:
        raise RuntimeError(f"original changed during conversion: {src}")
    out = probe(dst)
    meta = RunMetadata(
        slot=slot,
        stage="B.cfr",
        video_file=str(dst),
        video_sha256=sha256_file(dst),
        fps=fps,
        width=out.width,
        height=out.height,
        parameters={"source_file": str(src), "source_sha256": before, "crf": crf,
                    "source_probe": asdict(src_probe), "output_is_vfr": out.is_vfr},
    )
    meta.write(dst.with_suffix(".run.json"))
    return meta


@dataclass
class LensCalibration:
    camera_matrix: list[list[float]]
    dist_coeffs: list[float]
    image_size: tuple[int, int]
    rms_reprojection_px: float
    frames_used: int
    pattern_inner_corners: tuple[int, int]
    square_size_mm: float
    source_video: str
    source_sha256: str

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path) -> "LensCalibration":
        d = json.loads(path.read_text(encoding="utf-8"))
        d["image_size"] = tuple(d["image_size"])
        d["pattern_inner_corners"] = tuple(d["pattern_inner_corners"])
        return cls(**d)


def find_checkerboards(frames, pattern: tuple[int, int]) -> list[np.ndarray]:
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-3)
    found = []
    for frame in frames:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        ok, corners = cv2.findChessboardCorners(
            gray, pattern, cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE
        )
        if ok:
            found.append(cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria))
    return found


def calibrate_lens(frames, pattern: tuple[int, int], square_size_mm: float,
                   source_video: str = "", source_sha256: str = "",
                   min_frames: int = MIN_CHECKERBOARD_FRAMES) -> LensCalibration:
    """Estimate camera matrix and distortion from checkerboard frames (FR-02).

    pattern is the number of inner corners (columns, rows).
    """
    frames = list(frames)
    if not frames:
        raise ValueError("no frames given")
    corners = find_checkerboards(frames, pattern)
    if len(corners) < min_frames:
        raise ValueError(f"only {len(corners)} usable checkerboard frames; at least {min_frames} needed")
    obj = np.zeros((pattern[0] * pattern[1], 3), np.float32)
    obj[:, :2] = np.mgrid[0:pattern[0], 0:pattern[1]].T.reshape(-1, 2) * square_size_mm
    h, w = frames[0].shape[:2]
    rms, k, dist, _, _ = cv2.calibrateCamera([obj] * len(corners), corners, (w, h), None, None)
    return LensCalibration(
        camera_matrix=k.tolist(),
        dist_coeffs=dist.ravel().tolist(),
        image_size=(w, h),
        rms_reprojection_px=float(rms),
        frames_used=len(corners),
        pattern_inner_corners=tuple(pattern),
        square_size_mm=square_size_mm,
        source_video=source_video,
        source_sha256=source_sha256,
    )


def sample_frames(path: Path, every_s: float):
    """Yield frames every every_s seconds of media time."""
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {path}")
    next_t = 0.0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            if t + 1e-6 >= next_t:
                yield frame
                next_t = t + every_s
    finally:
        cap.release()


def undistort_maps(lens: LensCalibration):
    k = np.array(lens.camera_matrix)
    dist = np.array(lens.dist_coeffs)
    new_k, _ = cv2.getOptimalNewCameraMatrix(k, dist, lens.image_size, 0)
    return cv2.initUndistortRectifyMap(k, dist, None, new_k, lens.image_size, cv2.CV_16SC2), new_k


def undistort_video(src: Path, dst: Path, lens: LensCalibration, slot: str, crf: int = 18) -> RunMetadata:
    """Write an undistorted copy of a constant-frame-rate video (FR-03)."""
    _guard_output(src, dst)
    ffmpeg = _require("ffmpeg")
    before = sha256_file(src)
    src_probe = probe(src)
    if src_probe.is_vfr:
        raise ValueError(f"{src} is variable frame rate; convert it with to_cfr first")
    if (src_probe.width, src_probe.height) != tuple(lens.image_size):
        raise ValueError(f"video is {src_probe.width}x{src_probe.height}, lens calibration is {lens.image_size}")
    (map1, map2), new_k = undistort_maps(lens)
    w, h = lens.image_size
    dst.parent.mkdir(parents=True, exist_ok=True)
    enc = subprocess.Popen(
        [ffmpeg, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
         "-r", str(src_probe.r_frame_rate), "-i", "-", "-c:v", "libx264", "-crf", str(crf),
         "-preset", "medium", "-pix_fmt", "yuv420p", str(dst)],
        stdin=subprocess.PIPE,
    )
    cap = cv2.VideoCapture(str(src))
    n = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            enc.stdin.write(cv2.remap(frame, map1, map2, cv2.INTER_LINEAR).tobytes())
            n += 1
    finally:
        cap.release()
        enc.stdin.close()
        if enc.wait() != 0:
            raise RuntimeError("ffmpeg failed while writing the undistorted copy")
    if sha256_file(src) != before:
        raise RuntimeError(f"source changed during undistortion: {src}")
    meta = RunMetadata(
        slot=slot,
        stage="B.undistort",
        video_file=str(dst),
        video_sha256=sha256_file(dst),
        fps=src_probe.r_frame_rate,
        width=w,
        height=h,
        parameters={"source_file": str(src), "source_sha256": before, "frames": n, "crf": crf,
                    "lens_source_sha256": lens.source_sha256,
                    "new_camera_matrix": new_k.tolist()},
    )
    meta.write(dst.with_suffix(".run.json"))
    return meta
