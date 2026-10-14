"""Stage C: detection (ARCHITECTURE section 3, FR-04, FR-05).

YOLO only detects. It writes boxes, classes and confidences per processed
frame; counting, delay and everything else happen later from tracks.

- Weights are read from ``models/`` and never downloaded automatically.
- Model labels are mapped to project classes by an explicit table. A label
  that is neither mapped nor listed as ignored stops the run.
- Optional tiles (e.g. the far arm) are detected at full resolution and merged
  with the full-frame pass before tracking (ARCHITECTURE section 12). Tiles are
  listed one by one (``tiles``) or generated as a grid (``tile_grid``).
- Ultralytics runs offline: no update checks, no usage analytics, settings
  inside the repository. Nothing needs an internet connection.
- Input must be a constant-frame-rate copy, so time_s = frame / fps.
"""

from __future__ import annotations

import csv
import os
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import cv2
import numpy as np
import yaml

from pattom.boxes import nms
from pattom.paths import MODELS, REPO_ROOT, RUNS
from pattom.runmeta import RunMetadata, sha256_file

DETECTION_FIELDS = ["frame", "time_s", "class", "raw_label", "confidence", "x1", "y1", "x2", "y2", "pass"]


@dataclass
class DetectionConfig:
    weights: str
    class_map: dict[str, str]
    confidence_threshold: float
    process_fps: float
    ignore_labels: list[str] = field(default_factory=list)
    merge_iou: float = 0.6
    imgsz: int = 1280
    half: bool = True
    device: str | None = None
    tiles: list[list[int]] = field(default_factory=list)
    tile_imgsz: int = 1280
    # {size: px, overlap: px, region: [x1, y1, x2, y2] (optional, default whole frame)}
    tile_grid: dict[str, Any] | None = None
    # Drop a lower-scored box lying mostly inside a kept one (tile-edge halves); None = off.
    merge_inside: float | None = None

    @classmethod
    def load(cls, path: Path) -> "DetectionConfig":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        missing = {"weights", "class_map", "confidence_threshold", "process_fps"} - data.keys()
        if missing:
            raise ValueError(f"{path}: missing {sorted(missing)}")
        cfg = cls(**data)
        overlap = set(cfg.class_map) & set(cfg.ignore_labels)
        if overlap:
            raise ValueError(f"labels both mapped and ignored: {sorted(overlap)}")
        for t in cfg.tiles:
            if len(t) != 4 or not (t[0] < t[2] and t[1] < t[3]):
                raise ValueError(f"tile must be [x1, y1, x2, y2] with x1<x2, y1<y2: {t}")
        if cfg.tile_grid is not None:
            g = cfg.tile_grid
            if not isinstance(g, dict) or "size" not in g or not 0 <= g.get("overlap", 0) < g["size"]:
                raise ValueError("tile_grid needs size and 0 <= overlap < size, e.g. {size: 1280, overlap: 256}")
        if cfg.merge_inside is not None and not 0 < cfg.merge_inside <= 1:
            raise ValueError("merge_inside must be between 0 and 1, or null")
        return cfg

    def tiles_for(self, width: int, height: int) -> list[list[int]]:
        """The explicit tiles plus the grid, clipped to the frame."""
        tiles = [list(map(int, t)) for t in self.tiles]
        if self.tile_grid:
            g = self.tile_grid
            tiles += grid_tiles(width, height, int(g["size"]), int(g.get("overlap", 0)), g.get("region"))
        return tiles

    def weights_path(self) -> Path:
        p = Path(self.weights)
        p = p if p.is_absolute() else REPO_ROOT / p
        if MODELS.resolve() not in p.resolve().parents:
            raise ValueError(f"weights must be inside {MODELS}")
        if not p.exists():
            raise FileNotFoundError(f"{p} not found. Put the weights file in models/; nothing is downloaded.")
        return p


def _starts(lo: int, hi: int, size: int, overlap: int) -> list[int]:
    if hi - lo <= size:
        return [lo]
    out, s = [], lo
    while s + size < hi:
        out.append(s)
        s += size - overlap
    out.append(hi - size)
    return out


def grid_tiles(width: int, height: int, size: int, overlap: int, region: list[int] | None = None) -> list[list[int]]:
    """Square tiles covering the region (default the whole frame), neighbours
    overlapping by ``overlap`` pixels; the last row and column end at the edge."""
    x1, y1, x2, y2 = region or [0, 0, width, height]
    x1, y1, x2, y2 = max(0, x1), max(0, y1), min(width, x2), min(height, y2)
    return [[x, y, min(x + size, x2), min(y + size, y2)]
            for y in _starts(y1, y2, size, overlap) for x in _starts(x1, x2, size, overlap)]


def _offline_ultralytics() -> None:
    """Keep Ultralytics off the internet and its settings inside the repository."""
    cfg_dir = REPO_ROOT / ".ultralytics"
    (cfg_dir / "Ultralytics").mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("YOLO_CONFIG_DIR", str(cfg_dir))
    os.environ["YOLO_OFFLINE"] = "1"
    from ultralytics.utils import SETTINGS

    wanted = {"sync": False, "datasets_dir": str(REPO_ROOT / "labels"), "weights_dir": str(MODELS),
              "runs_dir": str(RUNS / "_ultralytics"), "clearml": False, "comet": False, "dvc": False,
              "mlflow": False, "raytune": False, "tensorboard": False, "wandb": False}
    if any(SETTINGS.get(k) != v for k, v in wanted.items()):
        SETTINGS.update(wanted)


class Detector(Protocol):
    name: str
    version: str

    def predict(self, image: np.ndarray, imgsz: int) -> list[tuple[np.ndarray, float, str]]:
        """Return (xyxy, confidence, raw_label) for one image."""


class UltralyticsDetector:
    """Wraps an Ultralytics YOLO model. Settings stay inside the repository."""

    def __init__(self, cfg: DetectionConfig):
        _offline_ultralytics()
        from ultralytics import YOLO  # heavy import, only when detection runs

        path = cfg.weights_path()
        self._model = YOLO(str(path))
        self._cfg = cfg
        self.name = path.name
        self.version = sha256_file(path)[:16]

    def predict(self, image: np.ndarray, imgsz: int) -> list[tuple[np.ndarray, float, str]]:
        r = self._model.predict(
            image, imgsz=imgsz, conf=self._cfg.confidence_threshold, quantize=16 if self._cfg.half else None,
            device=self._cfg.device, verbose=False,
        )[0]
        names = r.names
        b = r.boxes
        return [
            (xyxy, float(c), names[int(k)])
            for xyxy, c, k in zip(b.xyxy.cpu().numpy(), b.conf.cpu().numpy(), b.cls.cpu().numpy())
        ]


def detect_frame(image: np.ndarray, cfg: DetectionConfig, detector: Detector) -> list[dict[str, Any]]:
    """Full-frame pass plus tiles, merged by class-agnostic NMS."""
    boxes, scores, labels, passes = [], [], [], []
    for xyxy, conf, label in detector.predict(image, cfg.imgsz):
        boxes.append(np.asarray(xyxy, float)); scores.append(conf); labels.append(label); passes.append("full")
    tiles = cfg.tiles_for(image.shape[1], image.shape[0])
    for i, (x1, y1, x2, y2) in enumerate(tiles):
        crop = image[y1:y2, x1:x2]
        for xyxy, conf, label in detector.predict(crop, cfg.tile_imgsz):
            boxes.append(np.asarray(xyxy, float) + [x1, y1, x1, y1])
            scores.append(conf); labels.append(label); passes.append(f"tile{i}")
    if not boxes:
        return []
    arr = np.vstack(boxes)
    keep = nms(arr, np.array(scores), cfg.merge_iou, cfg.merge_inside) if tiles else range(len(boxes))
    return [
        {"xyxy": arr[i], "confidence": scores[i], "raw_label": labels[i], "pass": passes[i]}
        for i in keep
        if scores[i] >= cfg.confidence_threshold
    ]


def map_labels(dets: list[dict[str, Any]], cfg: DetectionConfig, ignored: Counter) -> list[dict[str, Any]]:
    out = []
    for d in dets:
        label = d["raw_label"]
        if label in cfg.class_map:
            out.append({**d, "class": cfg.class_map[label]})
        elif label in cfg.ignore_labels:
            ignored[label] += 1
        else:
            raise ValueError(
                f"model label {label!r} is neither in class_map nor in ignore_labels; "
                "decide how to treat it in the detection config"
            )
    return out


def run_detection(video: Path, slot: str, cfg: DetectionConfig, detector: Detector | None = None,
                  out_dir: Path | None = None, progress=None) -> Path:
    """Detect on a prepared (CFR) video. Writes detections.csv and run metadata.

    progress, if given, is called with a short text line every 100 processed frames.
    """
    from pattom.prepare import probe

    info = probe(video)
    if info.is_vfr:
        raise ValueError(f"{video} is variable frame rate; prepare it first (pattom cfr)")
    fps = info.r_frame_rate
    stride = max(1, round(fps / cfg.process_fps))
    detector = detector or UltralyticsDetector(cfg)
    out_dir = out_dir or RUNS / slot / video.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "detections.csv"
    ignored: Counter = Counter()
    cap = cv2.VideoCapture(str(video))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or None
    frame = n_processed = n_dets = 0
    try:
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(DETECTION_FIELDS)
            while True:
                ok, image = cap.read()
                if not ok:
                    break
                if frame % stride == 0:
                    for d in map_labels(detect_frame(image, cfg, detector), cfg, ignored):
                        x1, y1, x2, y2 = (round(float(v), 2) for v in d["xyxy"])
                        w.writerow([frame, round(frame / fps, 4), d["class"], d["raw_label"],
                                    round(d["confidence"], 4), x1, y1, x2, y2, d["pass"]])
                        n_dets += 1
                    n_processed += 1
                    if progress and n_processed % 100 == 0:
                        of = f"/{total}" if total else ""
                        progress(f"detect: frame {frame}{of}, {n_dets} boxes")
                frame += 1
    finally:
        cap.release()
    RunMetadata(
        slot=slot,
        stage="C.detection",
        video_file=str(video),
        video_sha256=sha256_file(video),
        fps=fps,
        width=info.width,
        height=info.height,
        model_name=detector.name,
        model_version=detector.version,
        confidence_threshold=cfg.confidence_threshold,
        tiling_settings={"tiles": cfg.tiles_for(info.width, info.height), "tile_grid": cfg.tile_grid,
                         "tile_imgsz": cfg.tile_imgsz, "merge_iou": cfg.merge_iou, "merge_inside": cfg.merge_inside}
        if cfg.tiles or cfg.tile_grid else None,
        parameters={"process_fps": cfg.process_fps, "frame_stride": stride, "imgsz": cfg.imgsz,
                    "half": cfg.half, "class_map": cfg.class_map, "frames_read": frame,
                    "frames_processed": n_processed, "detections": n_dets,
                    "ignored_label_counts": dict(ignored)},
    ).write(out_dir / "detections.run.json")
    return out
