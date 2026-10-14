"""E Review: flag frames worth checking, save corrected labels, keep a review log (FR-06, FR-07).

Flags (ARCHITECTURE section 5): low confidence, a class change within a track,
a track that vanishes away from the frame edge, detections in hard zones, and
a random sample, because confidence is not accuracy. Flagged frames are kept a
few seconds apart. The thresholds are tool settings, tuned on the test clip,
and are passed in.

Corrected labels are written in the YOLO training format (one image and one
text file per frame, class index and normalised centre and size) under
labels/<slot>/<video>/, with classes.txt fixing the class order. The review
log is a separate file. Splitting train and validation by time block is done
when training (T13), from the times in the log.
"""

from __future__ import annotations

import csv
import random
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from pattom.tables import read_csv, require, write_csv, write_meta

QUEUE_FIELDS = ["frame", "time_s", "reasons", "track_ids"]
LOG_FIELDS = ["date", "slot", "video", "frame", "time_s", "reason_flagged", "reviewer_action", "boxes"]


def flag_frames(tracks_csv: Path, summary_csv: Path, slot: str, params: dict[str, Any], out_dir: Path,
                frame_size: tuple[int, int], video_end_s: float | None, fps: float) -> Path:
    require(params, "low_confidence", "edge_margin_px", "random_frames", "seed", "min_gap_s",
            why="flag thresholds are tool settings tuned on the test clip")
    w, h = frame_size
    rows = read_csv(tracks_csv)
    by_track = defaultdict(list)
    for r in rows:
        by_track[int(r["track_id"])].append(r)
    flags: dict[int, dict[str, Any]] = {}
    if video_end_s is None:  # no detection record: the last tracked moment
        video_end_s = max((float(r["time_s"]) for r in rows), default=0.0)

    def add(frame: int, reason: str, tid: int | None = None):
        f = flags.setdefault(frame, {"frame": frame, "time_s": round(frame / fps, 3), "reasons": set(), "tracks": set()})
        f["reasons"].add(reason)
        if tid is not None:
            f["tracks"].add(tid)

    low = float(params["low_confidence"])
    for tid, obs in by_track.items():
        worst = min(obs, key=lambda r: float(r["confidence"]))
        if float(worst["confidence"]) < low:
            add(int(worst["frame"]), "low_confidence", tid)
    for s in read_csv(summary_csv):
        if int(s["class_changes"]) > 0:
            tid = int(s["track_id"])
            obs = by_track[tid]
            change = next((b for a, b in zip(obs, obs[1:]) if a["class"] != b["class"]), obs[0])
            add(int(change["frame"]), "class_change", tid)
    m = float(params["edge_margin_px"])
    for tid, obs in by_track.items():
        last = obs[-1]
        x1, y1, x2, y2 = (float(last[k]) for k in ("x1", "y1", "x2", "y2"))
        near_edge = x1 < m or y1 < m or x2 > w - m or y2 > h - m
        if not near_edge and float(last["time_s"]) < video_end_s - 1.0:
            add(int(last["frame"]), "vanished", tid)
    for zone in params.get("hard_zones") or []:
        poly = np.array(zone["polygon_px"], np.float32)
        for r in rows:
            u, v = (float(r["x1"]) + float(r["x2"])) / 2, float(r["y2"])
            if cv2.pointPolygonTest(poly, (u, v), False) >= 0:
                add(int(r["frame"]), f"hard_zone:{zone['name']}", int(r["track_id"]))
    frames = sorted({int(r["frame"]) for r in rows})
    rng = random.Random(int(params["seed"]))
    for f in rng.sample(frames, min(int(params["random_frames"]), len(frames))):
        add(f, "random_sample")
    gap = float(params["min_gap_s"])
    kept, last_t = [], -1e9
    for f in sorted(flags.values(), key=lambda x: x["time_s"]):
        if f["time_s"] - last_t >= gap or "random_sample" in f["reasons"]:
            kept.append(f)
            last_t = f["time_s"]
    out = write_csv(out_dir / "review_queue.csv", QUEUE_FIELDS,
                    [{"frame": f["frame"], "time_s": f["time_s"], "reasons": ";".join(sorted(f["reasons"])),
                      "track_ids": ";".join(map(str, sorted(f["tracks"])))} for f in kept])
    write_meta(out_dir / "review_queue.run.json", "E.review_flags", slot, {"tracks": tracks_csv},
               {**params, "flagged": len(flags), "kept": len(kept)})
    return out


def class_list(labels_dir: Path, classes: list[str]) -> list[str]:
    """The fixed class order in classes.txt; new classes are appended, never reordered."""
    f = labels_dir / "classes.txt"
    have = f.read_text(encoding="utf-8").split() if f.exists() else []
    for c in classes:
        if c not in have:
            have.append(c)
    labels_dir.mkdir(parents=True, exist_ok=True)
    f.write_text("\n".join(have) + "\n", encoding="utf-8")
    return have


def save_label(video: Path, frame: int, fps: float, boxes: list[dict[str, Any]], labels_dir: Path, slot: str,
               reason: str, action: str) -> Path:
    """Write the frame image, its YOLO label file and a review-log row."""
    cap = cv2.VideoCapture(str(video))
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame)
        ok, img = cap.read()
    finally:
        cap.release()
    if not ok:
        raise ValueError(f"could not read frame {frame} of {video}")
    h, w = img.shape[:2]
    order = class_list(labels_dir, [b["class"] for b in boxes])
    stem = f"{video.stem}_f{frame:07d}"
    (labels_dir / "images").mkdir(parents=True, exist_ok=True)
    (labels_dir / "labels").mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(labels_dir / "images" / f"{stem}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
    lines = []
    for b in boxes:
        x1, y1, x2, y2 = (float(v) for v in b["xyxy"])
        x1, x2 = sorted((max(0, x1), min(w, x2)))
        y1, y2 = sorted((max(0, y1), min(h, y2)))
        if x2 - x1 < 2 or y2 - y1 < 2:
            continue
        lines.append(f"{order.index(b['class'])} {(x1 + x2) / 2 / w:.6f} {(y1 + y2) / 2 / h:.6f} "
                     f"{(x2 - x1) / w:.6f} {(y2 - y1) / h:.6f}")
    label = labels_dir / "labels" / f"{stem}.txt"
    label.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    log = labels_dir / "review_log.csv"
    new = not log.exists()
    with open(log, "a", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if new:
            wr.writeheader()
        wr.writerow({"date": datetime.now(timezone.utc).isoformat(timespec="seconds"), "slot": slot,
                     "video": video.stem, "frame": frame, "time_s": round(frame / fps, 3), "reason_flagged": reason,
                     "reviewer_action": action, "boxes": len(lines)})
    return label
