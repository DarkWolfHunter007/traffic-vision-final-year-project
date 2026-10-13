"""Phase 02 detection primitives: mapping, preprocessing, tiling, and merge."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

import numpy as np

from backend.geometry import compute_ground_point


class DetectionError(ValueError):
    """Raised when a detection configuration or model output is invalid."""


@dataclass(frozen=True)
class RawDetection:
    class_id: int
    raw_class_name: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float

    def translated(self, x_offset: int, y_offset: int) -> "RawDetection":
        return RawDetection(
            class_id=self.class_id,
            raw_class_name=self.raw_class_name,
            confidence=self.confidence,
            x1=self.x1 + x_offset,
            y1=self.y1 + y_offset,
            x2=self.x2 + x_offset,
            y2=self.y2 + y_offset,
        )


@dataclass(frozen=True)
class Detection:
    class_id: int
    class_name: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def width_px(self) -> float:
        return self.x2 - self.x1

    @property
    def height_px(self) -> float:
        return self.y2 - self.y1

    @property
    def ground_x(self) -> float:
        return compute_ground_point(self.x1, self.y1, self.x2, self.y2)[0]

    @property
    def ground_y(self) -> float:
        return compute_ground_point(self.x1, self.y1, self.x2, self.y2)[1]


@dataclass(frozen=True)
class Tile:
    x: int
    y: int
    width: int
    height: int


class Detector(Protocol):
    def predict(self, image: np.ndarray, *, confidence: float, iou: float, image_size: int) -> Sequence[RawDetection]: ...


def map_detection(raw: RawDetection, class_mapping: dict[str, str]) -> Detection:
    """Map a model label to an explicitly configured canonical project class."""
    try:
        canonical_name = class_mapping[raw.raw_class_name]
    except KeyError as error:
        raise DetectionError(f"Model class '{raw.raw_class_name}' has no configured canonical mapping") from error
    if not canonical_name:
        raise DetectionError(f"Model class '{raw.raw_class_name}' maps to an empty canonical class")
    return Detection(
        class_id=raw.class_id,
        class_name=canonical_name,
        confidence=raw.confidence,
        x1=raw.x1,
        y1=raw.y1,
        x2=raw.x2,
        y2=raw.y2,
    )


def validate_roi_crop(roi_crop: object, image_width: int, image_height: int) -> tuple[int, int, int, int] | None:
    if roi_crop is None:
        return None
    if not isinstance(roi_crop, list) or len(roi_crop) != 4 or not all(isinstance(value, int) for value in roi_crop):
        raise DetectionError("detection.roi_crop must be null or [x1, y1, x2, y2] integer pixel coordinates")
    x1, y1, x2, y2 = roi_crop
    if not (0 <= x1 < x2 <= image_width and 0 <= y1 < y2 <= image_height):
        raise DetectionError("detection.roi_crop must lie inside the source frame")
    return x1, y1, x2, y2


def crop_image(image: np.ndarray, roi_crop: tuple[int, int, int, int] | None) -> tuple[np.ndarray, int, int]:
    if roi_crop is None:
        return image, 0, 0
    x1, y1, x2, y2 = roi_crop
    return image[y1:y2, x1:x2], x1, y1


def generate_tiles(image_width: int, image_height: int, tile_width: int, tile_height: int, overlap: float) -> list[Tile]:
    if tile_width <= 0 or tile_height <= 0:
        raise DetectionError("Tile dimensions must be positive")
    if not 0 <= overlap < 1:
        raise DetectionError("Tile overlap must be at least zero and below one")
    x_step = max(1, round(tile_width * (1 - overlap)))
    y_step = max(1, round(tile_height * (1 - overlap)))
    x_positions = list(range(0, max(image_width - tile_width, 0) + 1, x_step)) or [0]
    y_positions = list(range(0, max(image_height - tile_height, 0) + 1, y_step)) or [0]
    if x_positions[-1] + tile_width < image_width:
        x_positions.append(max(image_width - tile_width, 0))
    if y_positions[-1] + tile_height < image_height:
        y_positions.append(max(image_height - tile_height, 0))
    return [Tile(x, y, min(tile_width, image_width - x), min(tile_height, image_height - y)) for y in y_positions for x in x_positions]


def intersection_over_union(first: RawDetection, second: RawDetection) -> float:
    left, top = max(first.x1, second.x1), max(first.y1, second.y1)
    right, bottom = min(first.x2, second.x2), min(first.y2, second.y2)
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    union = (first.x2 - first.x1) * (first.y2 - first.y1) + (second.x2 - second.x1) * (second.y2 - second.y1) - intersection
    return intersection / union if union > 0 else 0.0


def merge_tile_detections(detections: Sequence[RawDetection], iou_threshold: float) -> list[RawDetection]:
    """Class-aware, deterministic NMS for duplicate detections from overlapping tiles."""
    ordered = sorted(
        detections,
        key=lambda item: (-item.confidence, item.class_id, item.raw_class_name, item.x1, item.y1, item.x2, item.y2),
    )
    accepted: list[RawDetection] = []
    for candidate in ordered:
        if all(
            candidate.class_id != existing.class_id or candidate.raw_class_name != existing.raw_class_name or intersection_over_union(candidate, existing) < iou_threshold
            for existing in accepted
        ):
            accepted.append(candidate)
    return accepted


class UltralyticsDetector:
    """Thin detection-only adapter; it deliberately never calls model.track()."""

    def __init__(self, model_path: Path, device: str) -> None:
        if not model_path.is_file():
            raise DetectionError(f"Configured model weights do not exist: {model_path}")
        try:
            from ultralytics import YOLO
        except ImportError as error:
            raise DetectionError("Ultralytics is not installed") from error
        self._model = YOLO(str(model_path))
        self._device = device

    def predict(self, image: np.ndarray, *, confidence: float, iou: float, image_size: int) -> Sequence[RawDetection]:
        result = self._model.predict(source=image, conf=confidence, iou=iou, imgsz=image_size, device=self._device, verbose=False)[0]
        names = result.names
        if result.boxes is None:
            return []
        return [
            RawDetection(
                class_id=int(box.cls.item()),
                raw_class_name=str(names[int(box.cls.item())]),
                confidence=float(box.conf.item()),
                x1=float(box.xyxy[0][0].item()),
                y1=float(box.xyxy[0][1].item()),
                x2=float(box.xyxy[0][2].item()),
                y2=float(box.xyxy[0][3].item()),
            )
            for box in result.boxes
        ]
