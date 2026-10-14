"""Stage C: detection (ARCHITECTURE section 3, FR-04, FR-05).

YOLO only detects. It writes boxes, classes and confidences per processed
frame; counting, delay and everything else happen later from tracks.

- Weights are read from ``models/`` and never downloaded automatically.
- Model labels are mapped to project classes by an explicit table. A label
  that is neither mapped nor listed as ignored stops the run.
- Optional tiles (e.g. the far arm) are detected at full resolution and merged
  with the full-frame pass before tracking (ARCHITECTURE section 12).
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
        return cfg

    def weights_path(self) -> Path:
        p = Path(self.weights)
        p = p if p.is_absolute() else REPO_ROOT / p
        if MODELS.resolve() not in p.resolve().parents:
            raise ValueError(f"weights must be inside {MODELS}")
        if not p.exists():
            raise FileNotFoundError(f"{p} not found. Put the weights file in models/; nothing is downloaded.")
        return p


class Detector(Protocol):
    name: str
    version: str

    def predict(self, image: np.ndarray, imgsz: int) -> list[tuple[np.ndarray, float, str]]:
        """Return (xyxy, confidence, raw_label) for one image."""


class UltralyticsDetector:
    """Wraps an Ultralytics YOLO model. Settings stay inside the repository."""

    def __init__(self, cfg: DetectionConfig):
        os.environ.setdefault("YOLO_CONFIG_DIR", str(REPO_ROOT / ".ultralytics"))
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
    for i, (x1, y1, x2, y2) in enumerate(cfg.tiles):
        crop = image[y1:y2, x1:x2]
        for xyxy, conf, label in detector.predict(crop, cfg.tile_imgsz):
            boxes.append(np.asarray(xyxy, float) + [x1, y1, x1, y1])
            scores.append(conf); labels.append(label); passes.append(f"tile{i}")
    if not boxes:
        return []
    arr = np.vstack(boxes)
    keep = nms(arr, np.array(scores), cfg.merge_iou) if cfg.tiles else range(len(boxes))
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
                  out_dir: Path | None = None) -> Path:
    """Detect on a prepared (CFR) video. Writes detections.csv and run metadata."""
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
        tiling_settings={"tiles": cfg.tiles, "tile_imgsz": cfg.tile_imgsz, "merge_iou": cfg.merge_iou}
        if cfg.tiles else None,
        parameters={"process_fps": cfg.process_fps, "frame_stride": stride, "imgsz": cfg.imgsz,
                    "half": cfg.half, "class_map": cfg.class_map, "frames_read": frame,
                    "frames_processed": n_processed, "detections": n_dets,
                    "ignored_label_counts": dict(ignored)},
    ).write(out_dir / "detections.run.json")
    return out
