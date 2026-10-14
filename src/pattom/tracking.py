"""Stage D: tracking with ByteTrack (ARCHITECTURE section 3, FR-04).

ByteTrack (Zhang et al., ECCV 2022) associates high-confidence detections
first, then uses low-confidence ones to keep existing tracks alive through
occlusion (buses, cables). Implemented here on the detections file so the
tracker can be re-run without re-running YOLO.

The tracker choice is open (O7: ByteTrack or BoT-SORT). Only ByteTrack is
implemented; the run metadata records it.

Outputs, per video:
- tracks.csv: one row per tracked box (ARCHITECTURE 4.2; ground columns are
  filled later by the ground mapping, never from raw pixels).
- track_summary.csv: one row per track with its majority class and the number
  of class changes, used by the review flags (FR-06).
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import yaml
from scipy.optimize import linear_sum_assignment

from pattom.boxes import iou_matrix
from pattom.kalman import KalmanXYAH, xyah_to_xyxy, xyxy_to_xyah
from pattom.runmeta import RunMetadata, sha256_file

TRACK_FIELDS = ["frame", "time_s", "track_id", "class", "confidence", "x1", "y1", "x2", "y2",
                "ground_x_m", "ground_y_m"]
SUMMARY_FIELDS = ["track_id", "first_time_s", "last_time_s", "n_boxes", "majority_class",
                  "class_changes", "classes_seen"]


@dataclass
class TrackerConfig:
    """ByteTrack settings. These are tool settings, tuned on the test clip."""

    high_thresh: float
    low_thresh: float
    new_track_thresh: float
    match_iou: float  # minimum IoU to accept a first-stage match
    low_match_iou: float  # minimum IoU for the low-confidence second stage
    track_buffer_s: float  # how long a lost track is kept before it is dropped
    name: str = "bytetrack"

    @classmethod
    def load(cls, path: Path) -> "TrackerConfig":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        cfg = cls(**data)
        if not 0 <= cfg.low_thresh < cfg.high_thresh <= 1:
            raise ValueError("need 0 <= low_thresh < high_thresh <= 1")
        if cfg.name != "bytetrack":
            raise ValueError(f"tracker {cfg.name!r} is not implemented (only bytetrack)")
        return cfg


@dataclass
class _Track:
    track_id: int
    mean: np.ndarray
    cov: np.ndarray
    last_frame: int
    confirmed: bool = False
    hits: int = 1
    classes: list[str] = field(default_factory=list)

    def box(self) -> np.ndarray:
        return xyah_to_xyxy(self.mean)


def _match(tracks: list[_Track], boxes: np.ndarray, min_iou: float):
    if not tracks or len(boxes) == 0:
        return [], list(range(len(tracks))), list(range(len(boxes)))
    iou = iou_matrix(np.array([t.box() for t in tracks]), boxes)
    rows, cols = linear_sum_assignment(-iou)
    pairs = [(r, c) for r, c in zip(rows, cols) if iou[r, c] >= min_iou]
    mr, mc = {r for r, _ in pairs}, {c for _, c in pairs}
    return pairs, [i for i in range(len(tracks)) if i not in mr], [j for j in range(len(boxes)) if j not in mc]


class ByteTracker:
    def __init__(self, cfg: TrackerConfig, fps: float):
        self.cfg = cfg
        self.kf = KalmanXYAH()
        self.max_lost_frames = max(1, round(cfg.track_buffer_s * fps))
        self.tracks: list[_Track] = []
        self._next_id = 1

    def update(self, frame: int, boxes: np.ndarray, scores: np.ndarray, classes: list[str]):
        """Advance to `frame`. Returns [(track_id, det_index)] for matched detections."""
        boxes = np.asarray(boxes, float).reshape(-1, 4)
        scores = np.asarray(scores, float)
        for t in self.tracks:
            # one predict step per elapsed processed frame keeps velocity in step with the stride
            t.mean, t.cov = self.kf.predict(t.mean, t.cov)

        high = np.flatnonzero(scores >= self.cfg.high_thresh)
        low = np.flatnonzero((scores >= self.cfg.low_thresh) & (scores < self.cfg.high_thresh))
        out: list[tuple[int, int]] = []

        def apply(t: _Track, j: int) -> None:
            t.mean, t.cov = self.kf.update(t.mean, t.cov, xyxy_to_xyah(boxes[j]))
            t.last_frame = frame
            t.hits += 1
            t.confirmed = True
            t.classes.append(classes[j])
            out.append((t.track_id, int(j)))

        # Stage 1: all live tracks against high-confidence boxes.
        pairs, un_t, un_d = _match(self.tracks, boxes[high], self.cfg.match_iou)
        for r, c in pairs:
            apply(self.tracks[r], high[c])
        # Stage 2: remaining confirmed tracks against low-confidence boxes.
        rest = [self.tracks[i] for i in un_t if self.tracks[i].confirmed]
        pairs2, _, _ = _match(rest, boxes[low], self.cfg.low_match_iou)
        for r, c in pairs2:
            apply(rest[r], low[c])
        # New tracks from unmatched high-confidence boxes.
        for c in un_d:
            j = high[c]
            if scores[j] < self.cfg.new_track_thresh:
                continue
            mean, cov = self.kf.initiate(xyxy_to_xyah(boxes[j]))
            t = _Track(self._next_id, mean, cov, frame, classes=[classes[j]])
            self._next_id += 1
            self.tracks.append(t)
            out.append((t.track_id, int(j)))
        # Drop unconfirmed tracks that missed once, and tracks lost too long.
        self.tracks = [
            t for t in self.tracks
            if (t.confirmed or t.last_frame == frame) and frame - t.last_frame <= self.max_lost_frames
        ]
        return out


def _read_detections(path: Path):
    by_frame: dict[int, list[dict]] = defaultdict(list)
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            by_frame[int(row["frame"])].append(row)
    return by_frame


def run_tracking(detections_csv: Path, cfg: TrackerConfig, out_dir: Path | None = None) -> Path:
    det_meta = json.loads(detections_csv.with_suffix(".run.json").read_text(encoding="utf-8"))
    fps = det_meta["fps"]
    stride = det_meta["parameters"]["frame_stride"]
    out_dir = out_dir or detections_csv.parent
    by_frame = _read_detections(detections_csv)
    # The tracker steps once per processed frame, so its buffer is in processed frames.
    tracker = ByteTracker(cfg, fps / stride)
    per_track: dict[int, list[tuple[float, str]]] = defaultdict(list)
    n_rows = 0
    out = out_dir / "tracks.csv"
    frames = range(0, (max(by_frame) + 1) if by_frame else 0, stride)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(TRACK_FIELDS)
        for step, frame in enumerate(frames):
            rows = by_frame.get(frame, [])
            boxes = np.array([[float(r[k]) for k in ("x1", "y1", "x2", "y2")] for r in rows]).reshape(-1, 4)
            scores = np.array([float(r["confidence"]) for r in rows])
            classes = [r["class"] for r in rows]
            for tid, j in tracker.update(step, boxes, scores, classes):
                r = rows[j]
                w.writerow([frame, r["time_s"], tid, r["class"], r["confidence"],
                            r["x1"], r["y1"], r["x2"], r["y2"], "", ""])
                per_track[tid].append((float(r["time_s"]), r["class"]))
                n_rows += 1
    with open(out_dir / "track_summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(SUMMARY_FIELDS)
        for tid, obs in sorted(per_track.items()):
            seq = [c for _, c in obs]
            changes = sum(a != b for a, b in zip(seq, seq[1:]))
            counts = Counter(seq)
            w.writerow([tid, obs[0][0], obs[-1][0], len(obs), counts.most_common(1)[0][0], changes,
                        ";".join(sorted(counts))])
    RunMetadata(
        slot=det_meta["slot"],
        stage="D.tracking",
        video_file=det_meta["video_file"],
        video_sha256=det_meta["video_sha256"],
        fps=fps,
        width=det_meta["width"],
        height=det_meta["height"],
        model_name=det_meta["model_name"],
        model_version=det_meta["model_version"],
        tracker=cfg.name,
        confidence_threshold=det_meta["confidence_threshold"],
        tiling_settings=det_meta["tiling_settings"],
        parameters={"tracker_config": asdict(cfg), "detections_sha256": sha256_file(detections_csv),
                    "track_rows": n_rows, "tracks": len(per_track)},
    ).write(out_dir / "tracks.run.json")
    return out
