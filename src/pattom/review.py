"""E Review: flag tracks worth checking and save a cropped picture of each (FR-06).

Flags (ARCHITECTURE section 5):
- low_confidence: the track's weakest box is below the threshold;
- class_change: the track's class changes along the way;
- vanished: the track ends away from the frame edge before the video ends
  (the tracker lost a vehicle that is still in view);
- short: the track has very few boxes (often a false detection);
- random: a random sample of the other tracks, because confidence is not accuracy.

The thresholds are tool settings, tuned on the test clip; they are not study
values and never enter a result. Each flag gets a crop of the vehicle at the
flagged frame with its box drawn, under review/crops/.
"""

from __future__ import annotations

import csv
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

import cv2

FLAG_FIELDS = ["flag_id", "track_id", "reason", "detail", "frame", "time_s", "class", "confidence",
               "x1", "y1", "x2", "y2", "crop"]


def _read(path: Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def find_flags(tracks_csv: Path, frame_w: int, frame_h: int, video_end_s: float, p: dict[str, Any]) -> list[dict]:
    by_track: dict[int, list[dict[str, str]]] = defaultdict(list)
    for r in _read(tracks_csv):
        by_track[int(r["track_id"])].append(r)
    low, margin = float(p["low_confidence"]), float(p["edge_margin_px"])
    min_boxes, n_random = int(p["min_boxes"]), int(p["random_tracks"])
    flags: list[dict] = []

    def add(tid: int, reason: str, detail: str, row: dict[str, str]) -> None:
        flags.append({"track_id": tid, "reason": reason, "detail": detail, "frame": int(row["frame"]),
                      "time_s": float(row["time_s"]), "class": row["class"], "confidence": float(row["confidence"]),
                      **{k: float(row[k]) for k in ("x1", "y1", "x2", "y2")}})

    flagged = set()
    for tid, obs in sorted(by_track.items()):
        obs.sort(key=lambda r: int(r["frame"]))
        worst = min(obs, key=lambda r: float(r["confidence"]))
        if float(worst["confidence"]) < low:
            add(tid, "low_confidence", f"weakest box {float(worst['confidence']):.2f} < {low}", worst)
            flagged.add(tid)
        classes = [r["class"] for r in obs]
        changes = [i for i in range(1, len(classes)) if classes[i] != classes[i - 1]]
        if changes:
            seen = sorted(set(classes), key=classes.index)
            add(tid, "class_change", "seen as " + " -> ".join(seen), obs[changes[0]])
            flagged.add(tid)
        last = obs[-1]
        x1, y1, x2, y2 = (float(last[k]) for k in ("x1", "y1", "x2", "y2"))
        near_edge = x1 < margin or y1 < margin or x2 > frame_w - margin or y2 > frame_h - margin
        if not near_edge and float(last["time_s"]) < video_end_s - 0.5:
            add(tid, "vanished", f"lost at {float(last['time_s']):.1f} s, away from the frame edge", last)
            flagged.add(tid)
        if len(obs) < min_boxes:
            add(tid, "short", f"only {len(obs)} box(es)", obs[len(obs) // 2])
            flagged.add(tid)
    rest = [t for t in sorted(by_track) if t not in flagged]
    for tid in random.Random(int(p["seed"])).sample(rest, min(n_random, len(rest))):
        obs = by_track[tid]
        add(tid, "random", "random check (confidence is not accuracy)", obs[len(obs) // 2])
    return flags


def _crop(image, f: dict, out: Path) -> None:
    h, w = image.shape[:2]
    x1, y1, x2, y2 = int(f["x1"]), int(f["y1"]), int(f["x2"]), int(f["y2"])
    pad = max(40, int(0.6 * max(x2 - x1, y2 - y1)))
    cx1, cy1, cx2, cy2 = max(0, x1 - pad), max(0, y1 - pad), min(w, x2 + pad), min(h, y2 + pad)
    crop = image[cy1:cy2, cx1:cx2].copy()
    cv2.rectangle(crop, (x1 - cx1, y1 - cy1), (x2 - cx1, y2 - cy1), (0, 200, 255), 3)
    label = f"#{f['track_id']} {f['class']} {f['confidence']:.2f}"
    cv2.putText(crop, label, (x1 - cx1, max(18, y1 - cy1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2, cv2.LINE_AA)
    if crop.shape[1] > 480:
        crop = cv2.resize(crop, None, fx=480 / crop.shape[1], fy=480 / crop.shape[1])
    cv2.imwrite(str(out), crop, [cv2.IMWRITE_JPEG_QUALITY, 85])


def run_review(tracks_csv: Path, video: Path, params: dict[str, Any]) -> Path:
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise ValueError(f"cannot open video {video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    end_s = (cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0) / fps
    flags = find_flags(tracks_csv, w, h, end_s, params)
    # Keep the review manageable on long videos: at most max_per_reason flags per reason
    # (a seeded random pick), and say how many were left out.
    cap_n = int(params.get("max_per_reason") or 0)
    dropped: dict[str, int] = {}
    if cap_n > 0:
        by_reason: dict[str, list[dict]] = defaultdict(list)
        for f in flags:
            by_reason[f["reason"]].append(f)
        rng = random.Random(int(params["seed"]))
        flags = []
        for reason, fs in by_reason.items():
            if len(fs) > cap_n:
                dropped[reason] = len(fs) - cap_n
                fs = rng.sample(fs, cap_n)
            flags.extend(fs)
        flags.sort(key=lambda f: (f["time_s"], f["track_id"]))
    out_dir = Path(tracks_csv).parent / "review"
    crops = out_dir / "crops"
    crops.mkdir(parents=True, exist_ok=True)
    for old in crops.glob("*.jpg"):
        old.unlink()
    by_frame: dict[int, list[dict]] = defaultdict(list)
    for i, f in enumerate(flags, start=1):
        f["flag_id"] = i
        f["crop"] = f"review/crops/flag_{i:04d}.jpg"
        by_frame[f["frame"]].append(f)
    for frame in sorted(by_frame):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame)
        ok, image = cap.read()
        if not ok:
            continue
        for f in by_frame[frame]:
            _crop(image, f, Path(tracks_csv).parent / f["crop"])
    cap.release()
    out = out_dir / "review_flags.csv"
    with open(out, "w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=FLAG_FIELDS)
        wr.writeheader()
        wr.writerows(sorted(flags, key=lambda f: f["flag_id"]))
    counts: dict[str, int] = defaultdict(int)
    for f in flags:
        counts[f["reason"]] += 1
    (out_dir / "review_flags.run.json").write_text(json.dumps({
        "stage": "E.review", "video_file": str(video), "tracks": str(tracks_csv), "parameters": {
            **params, "notes": [f"{len(flags)} flag(s): " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
                                + ". Thresholds are tool settings, not study values."]
            + ([f"Left out to keep the review short (random pick kept): {dropped}"] if dropped else [])}},
        indent=2), encoding="utf-8")
    print(f"review: {len(flags)} flag(s) on {len({f['track_id'] for f in flags})} track(s): {dict(counts)}", flush=True)
    return out
