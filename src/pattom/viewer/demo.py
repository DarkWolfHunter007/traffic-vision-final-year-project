"""A synthetic run for trying the viewer without footage.

Writes an ffmpeg test-pattern video and made-up moving boxes under slot
``demo``. Nothing here is traffic data: the run metadata says so, and the
slot name keeps it apart from real slots.
"""

from __future__ import annotations

import csv
import shutil
import subprocess
from pathlib import Path

from pattom.paths import REPO_ROOT
from pattom.runmeta import RunMetadata, sha256_file

NOTE = "SYNTHETIC demo for the viewer: test-pattern video and made-up boxes. Not traffic data."
W, H, FPS, SECONDS, STRIDE = 960, 540, 30, 6, 2
# (track_id, class, start box x1,y1,x2,y2, velocity px/s, first s, last s)
OBJECTS = [
    (1, "car", (40, 300, 180, 380), (110, 0), 0.0, 5.0),
    (2, "two_wheeler", (800, 120, 850, 190), (-90, 25), 0.5, 5.5),
    (3, "bus", (300, 40, 520, 150), (0, 45), 1.0, 6.0),
    (4, "truck", (600, 380, 760, 470), (-60, -10), 2.0, 6.0),
]


def make_demo(repo_root: Path = REPO_ROOT) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is not on PATH")
    video = repo_root / "data" / "cfr" / "demo_clip.mp4"
    video.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size={W}x{H}:rate={FPS}",
                    "-t", str(SECONDS), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True)
    out = repo_root / "runs" / "demo" / "demo_clip"
    out.mkdir(parents=True, exist_ok=True)
    det_rows, trk_rows, summary = [], [], []
    for tid, cls, (x1, y1, x2, y2), (vx, vy), t0, t1 in OBJECTS:
        n = 0
        for frame in range(0, FPS * SECONDS, STRIDE):
            t = frame / FPS
            if not t0 <= t <= t1:
                continue
            dx, dy = vx * (t - t0), vy * (t - t0)
            box = [round(v, 2) for v in (x1 + dx, y1 + dy, x2 + dx, y2 + dy)]
            conf = round(0.35 + 0.6 * ((frame // STRIDE + tid) % 7) / 6, 3)
            det_rows.append([frame, round(t, 4), cls, cls, conf, *box, "full"])
            trk_rows.append([frame, round(t, 4), tid, cls, conf, *box, "", ""])
            n += 1
        summary.append([tid, t0, t1, n, cls, 1 if tid == 2 else 0, cls])
    det_rows.sort(key=lambda r: r[0])
    trk_rows.sort(key=lambda r: r[0])
    _write(out / "detections.csv", ["frame", "time_s", "class", "raw_label", "confidence",
                                    "x1", "y1", "x2", "y2", "pass"], det_rows)
    _write(out / "tracks.csv", ["frame", "time_s", "track_id", "class", "confidence",
                                "x1", "y1", "x2", "y2", "ground_x_m", "ground_y_m"], trk_rows)
    _write(out / "track_summary.csv", ["track_id", "first_time_s", "last_time_s", "n_boxes", "majority_class",
                                       "class_changes", "classes_seen"], summary)
    for stage, name in (("C.detection", "detections"), ("D.tracking", "tracks")):
        RunMetadata(slot="demo", stage=stage, video_file=str(video.relative_to(repo_root)),
                    video_sha256=sha256_file(video), fps=FPS, width=W, height=H, model_name="synthetic",
                    tracker="synthetic" if name == "tracks" else None,
                    parameters={"frame_stride": STRIDE}, notes=NOTE).write(out / f"{name}.run.json")
    return out


def _write(path: Path, header: list[str], rows: list[list]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
