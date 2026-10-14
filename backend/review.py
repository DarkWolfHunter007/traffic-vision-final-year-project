"""Phase 10 pure logic: uncertainty evaluation, bounding box validation, and review models.

Provides deterministic candidate identification, geometric containment checks,
class label enforcement, and temporal snippet window calculations.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import json
import math
from typing import Any


@dataclass(frozen=True)
class ReviewBox:
    """Canonical pixel bounding box representation [x1, y1, x2, y2]."""

    x1: float
    y1: float
    x2: float
    y2: float

    def to_dict(self) -> dict[str, float]:
        return {
            "x1": round(float(self.x1), 3),
            "y1": round(float(self.y1), 3),
            "x2": round(float(self.x2), 3),
            "y2": round(float(self.y2), 3),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ReviewBox:
        for k in ("x1", "y1", "x2", "y2"):
            if k not in data:
                raise ValueError(f"Missing required bounding box coordinate '{k}'")
        return cls(
            x1=float(data["x1"]),
            y1=float(data["y1"]),
            x2=float(data["x2"]),
            y2=float(data["y2"]),
        )

    @classmethod
    def from_json(cls, raw: str) -> ReviewBox:
        data = json.loads(raw)
        return cls.from_dict(data)

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def area(self) -> float:
        return self.width * self.height


@dataclass(frozen=True)
class UncertaintyCandidate:
    """An identified uncertain detection or track observation flagged for human review."""

    candidate_id: str
    source_type: str  # 'detection' | 'track'
    item_id: str  # detection_id or track_observation_id
    track_id: int | None
    frame_number: int
    timestamp_s: float
    predicted_class: str | None
    confidence: float
    bbox: ReviewBox
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "source_type": self.source_type,
            "item_id": self.item_id,
            "track_id": self.track_id,
            "frame_number": self.frame_number,
            "timestamp_s": round(self.timestamp_s, 4),
            "predicted_class": self.predicted_class,
            "confidence": round(self.confidence, 4),
            "bbox": self.bbox.to_dict(),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ManualReview:
    """Dataclass matching canonical manual_reviews table row."""

    review_id: str
    run_id: str
    video_id: str
    track_id: int | None
    detection_id: str | None
    frame_number: int
    timestamp_s: float
    original_class: str | None
    corrected_class: str | None
    original_bbox_json: str | None
    corrected_bbox_json: str | None
    reason: str
    review_status: str
    reviewer: str
    reviewed_at: str
    snippet_path: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "review_id": self.review_id,
            "run_id": self.run_id,
            "video_id": self.video_id,
            "track_id": self.track_id,
            "detection_id": self.detection_id,
            "frame_number": self.frame_number,
            "timestamp_s": round(self.timestamp_s, 4),
            "original_class": self.original_class,
            "corrected_class": self.corrected_class,
            "original_bbox_json": self.original_bbox_json,
            "corrected_bbox_json": self.corrected_bbox_json,
            "reason": self.reason,
            "review_status": self.review_status,
            "reviewer": self.reviewer,
            "reviewed_at": self.reviewed_at,
            "snippet_path": self.snippet_path,
        }


def validate_bounding_box(
    bbox: ReviewBox | Mapping[str, Any] | Sequence[float] | None,
    frame_width: int | float | None = None,
    frame_height: int | float | None = None,
) -> ReviewBox:
    """Validate bounding box geometry and frame boundaries.

    Ensures coordinates are finite numbers, x1 < x2, y1 < y2, width and height > 0,
    non-negative, and strictly inside the frame [0, frame_width] x [0, frame_height]
    when frame dimensions are provided.
    """
    if bbox is None:
        raise ValueError("Bounding box cannot be None")

    if isinstance(bbox, ReviewBox):
        x1, y1, x2, y2 = bbox.x1, bbox.y1, bbox.x2, bbox.y2
    elif isinstance(bbox, Mapping):
        for k in ("x1", "y1", "x2", "y2"):
            if k not in bbox:
                raise ValueError(f"Missing required coordinate '{k}' in bounding box")
        x1, y1, x2, y2 = float(bbox["x1"]), float(bbox["y1"]), float(bbox["x2"]), float(bbox["y2"])
    elif isinstance(bbox, (list, tuple)):
        if len(bbox) != 4:
            raise ValueError(f"Bounding box tuple/list must have 4 elements (x1, y1, x2, y2), got {len(bbox)}")
        x1, y1, x2, y2 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
    else:
        raise ValueError(f"Unsupported bounding box type: {type(bbox)}")

    # Check finite numbers
    for val, name in ((x1, "x1"), (y1, "y1"), (x2, "x2"), (y2, "y2")):
        if math.isnan(val) or math.isinf(val):
            raise ValueError(f"Bounding box coordinate {name} must be a finite real number, got {val}")

    # Check non-negative
    if x1 < 0:
        raise ValueError(f"Bounding box x1 cannot be negative: {x1}")
    if y1 < 0:
        raise ValueError(f"Bounding box y1 cannot be negative: {y1}")

    # Check non-inverted and non-zero area
    if x1 >= x2:
        raise ValueError(f"Bounding box x1 ({x1}) must be strictly less than x2 ({x2})")
    if y1 >= y2:
        raise ValueError(f"Bounding box y1 ({y1}) must be strictly less than y2 ({y2})")

    # Check frame containment
    if frame_width is not None and frame_width > 0:
        if x2 > frame_width:
            raise ValueError(f"Bounding box x2 ({x2}) extends beyond frame width ({frame_width})")
        if x1 > frame_width:
            raise ValueError(f"Bounding box x1 ({x1}) extends beyond frame width ({frame_width})")

    if frame_height is not None and frame_height > 0:
        if y2 > frame_height:
            raise ValueError(f"Bounding box y2 ({y2}) extends beyond frame height ({frame_height})")
        if y1 > frame_height:
            raise ValueError(f"Bounding box y1 ({y1}) extends beyond frame height ({frame_height})")

    return ReviewBox(x1=x1, y1=y1, x2=x2, y2=y2)


def validate_class_label(
    class_name: str | None,
    allowed_classes: Sequence[str] | None = None,
) -> str | None:
    """Validate vehicle class against allowed classes list."""
    if class_name is None:
        return None
    if not isinstance(class_name, str) or not class_name.strip():
        raise ValueError("Vehicle class must be a non-empty string")
    normalized = class_name.strip()
    if allowed_classes is not None:
        if normalized not in allowed_classes:
            raise ValueError(
                f"Vehicle class '{normalized}' is not allowed; must be one of: {list(allowed_classes)}"
            )
    return normalized


def validate_status_transition(
    current_status: str | None,
    new_status: str,
    allowed_statuses: Sequence[str] = ("pending", "approved", "rejected"),
) -> str:
    """Validate review status transition."""
    if not isinstance(new_status, str) or not new_status.strip():
        raise ValueError("Review status must be a non-empty string")
    normalized = new_status.strip().lower()
    if normalized not in allowed_statuses:
        raise ValueError(
            f"Invalid review status '{normalized}'; must be one of: {list(allowed_statuses)}"
        )
    return normalized


def compute_snippet_window(
    timestamp_s: float,
    duration_s: float | None = None,
    before_s: float = 1.0,
    after_s: float = 1.0,
) -> tuple[float, float]:
    """Compute clamped snippet time window [start_s, end_s]."""
    if before_s < 0:
        raise ValueError(f"snippet before_s must be non-negative, got {before_s}")
    if after_s < 0:
        raise ValueError(f"snippet after_s must be non-negative, got {after_s}")
    if timestamp_s < 0:
        raise ValueError(f"timestamp_s must be non-negative, got {timestamp_s}")

    start_s = max(0.0, timestamp_s - before_s)
    end_s = timestamp_s + after_s
    if duration_s is not None and duration_s > 0:
        end_s = min(float(duration_s), end_s)
    if start_s > end_s:
        start_s = end_s
    return round(start_s, 4), round(end_s, 4)


def _row_val(row: Any, key: str, default: Any = None) -> Any:
    try:
        val = row[key]
        return val if val is not None else default
    except (KeyError, IndexError, TypeError):
        return default


def identify_uncertain_detections(
    detections: Iterable[Mapping[str, Any] | Any],
    confidence_threshold: float = 0.50,
) -> list[UncertaintyCandidate]:
    """Identify detections with confidence at or below the threshold."""
    candidates: list[UncertaintyCandidate] = []
    for d in detections:
        conf = float(d["confidence"])
        if conf <= confidence_threshold:
            bbox = ReviewBox(
                x1=float(d["x1"]),
                y1=float(d["y1"]),
                x2=float(d["x2"]),
                y2=float(d["y2"]),
            )
            class_val = _row_val(d, "class_name", "")
            candidates.append(
                UncertaintyCandidate(
                    candidate_id=f"det_{d['detection_id']}",
                    source_type="detection",
                    item_id=str(d["detection_id"]),
                    track_id=None,
                    frame_number=int(d["frame_number"]),
                    timestamp_s=float(d["timestamp_s"]),
                    predicted_class=str(class_val) if class_val else "",
                    confidence=conf,
                    bbox=bbox,
                    reason="low_confidence",
                )
            )
    return candidates


def identify_uncertain_tracks(
    tracks: Iterable[Mapping[str, Any] | Any],
    confidence_threshold: float = 0.50,
) -> list[UncertaintyCandidate]:
    """Identify track observations with confidence at or below the threshold."""
    candidates: list[UncertaintyCandidate] = []
    for t in tracks:
        raw_conf = _row_val(t, "confidence")
        conf = float(raw_conf) if raw_conf is not None else 0.0
        if conf <= confidence_threshold:
            x1 = float(_row_val(t, "x1", 0.0))
            y1 = float(_row_val(t, "y1", 0.0))
            x2 = float(_row_val(t, "x2", 0.0))
            y2 = float(_row_val(t, "y2", 0.0))
            bbox = ReviewBox(x1=x1, y1=y1, x2=x2, y2=y2)
            obs_id = str(_row_val(t, "track_observation_id", ""))
            v_class = _row_val(t, "vehicle_class")
            trk_id = _row_val(t, "track_id")
            candidates.append(
                UncertaintyCandidate(
                    candidate_id=f"trk_{obs_id}",
                    source_type="track",
                    item_id=obs_id,
                    track_id=int(trk_id) if trk_id is not None else None,
                    frame_number=int(t["frame_number"]),
                    timestamp_s=float(t["timestamp_s"]),
                    predicted_class=str(v_class) if v_class else None,
                    confidence=conf,
                    bbox=bbox,
                    reason="low_confidence",
                )
            )
    return candidates

