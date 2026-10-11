"""Phase 03 ByteTrack primitives: cadence conversion, batch adapter, tracker adapter, and class resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Protocol, Sequence

import numpy as np

from backend.detection import Detection


class TrackingError(ValueError):
    """Raised when a tracking configuration or input is invalid."""


def cadence_to_frames(buffer_seconds: float, fps: float, frame_stride: int) -> int:
    """Convert an intended duration in seconds into integer frames based on effective cadence."""
    if buffer_seconds <= 0:
        raise TrackingError("track_buffer_seconds must be positive")
    if fps <= 0:
        raise TrackingError("Nominal FPS must be positive")
    if frame_stride <= 0:
        raise TrackingError("frame_stride must be positive")
    effective_fps = fps / frame_stride
    return max(1, round(buffer_seconds * effective_fps))


@dataclass(frozen=True)
class TrackObservation:
    track_id: int
    frame_number: int
    timestamp_s: float
    vehicle_class: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float
    ground_x: float
    ground_y: float
    trajectory_status: str = "complete"


@dataclass
class TrackingMetrics:
    total_tracks: int = 0
    active_tracks: int = 0
    total_observations: int = 0
    id_switches: int | None = None  # Explicitly None (unmeasured) when ground truth identities are unavailable


class DetectionBatch:
    """NumPy-backed detections exposing xywh, conf, and cls with boolean indexing."""

    def __init__(
        self,
        xyxy: Sequence[Sequence[float]] | np.ndarray,
        conf: Sequence[float] | np.ndarray,
        cls: Sequence[float | int] | np.ndarray,
        class_names: Sequence[str] | None = None,
    ) -> None:
        self.xyxy = np.asarray(xyxy, dtype=np.float32).reshape(-1, 4) if len(xyxy) else np.empty((0, 4), dtype=np.float32)
        self.conf = np.asarray(conf, dtype=np.float32)
        self.cls = np.asarray(cls, dtype=np.float32)
        self.class_names = list(class_names or [])

    @property
    def xywh(self) -> np.ndarray:
        if len(self.xyxy) == 0:
            return np.empty((0, 4), dtype=np.float32)
        x1 = self.xyxy[:, 0]
        y1 = self.xyxy[:, 1]
        x2 = self.xyxy[:, 2]
        y2 = self.xyxy[:, 3]
        return np.stack([(x1 + x2) / 2.0, (y1 + y2) / 2.0, x2 - x1, y2 - y1], axis=1)

    def __getitem__(self, mask: np.ndarray) -> "DetectionBatch":
        selected_names = [self.class_names[i] for i, selected in enumerate(mask) if selected] if self.class_names else []
        return DetectionBatch(self.xyxy[mask], self.conf[mask], self.cls[mask], selected_names)

    def __len__(self) -> int:
        return len(self.conf)


class Tracker(Protocol):
    def update(
        self,
        frame_number: int,
        timestamp_s: float,
        detections: Sequence[Detection],
    ) -> Sequence[TrackObservation]: ...

    @property
    def metrics(self) -> TrackingMetrics: ...


class ByteTrackerAdapter:
    """Adapter wrapping Ultralytics BYTETracker directly without model.track()."""

    def __init__(
        self,
        *,
        track_high_thresh: float = 0.5,
        track_low_thresh: float = 0.1,
        new_track_thresh: float = 0.6,
        match_thresh: float = 0.8,
        track_buffer_frames: int = 30,
        fuse_score: bool = True,
    ) -> None:
        try:
            from ultralytics.trackers.byte_tracker import BYTETracker
        except ImportError as error:
            raise TrackingError("Ultralytics tracking dependencies are not installed") from error

        args = SimpleNamespace(
            track_high_thresh=track_high_thresh,
            track_low_thresh=track_low_thresh,
            new_track_thresh=new_track_thresh,
            track_buffer=track_buffer_frames,
            match_thresh=match_thresh,
            fuse_score=fuse_score,
        )
        self._tracker = BYTETracker(args)
        self._all_track_ids: set[int] = set()
        self._total_observations: int = 0

    def update(
        self,
        frame_number: int,
        timestamp_s: float,
        detections: Sequence[Detection],
    ) -> list[TrackObservation]:
        if detections:
            xyxy = [[d.x1, d.y1, d.x2, d.y2] for d in detections]
            confs = [d.confidence for d in detections]
            clss = [d.class_id for d in detections]
            names = [d.class_name for d in detections]
            batch = DetectionBatch(xyxy, confs, clss, names)
        else:
            batch = DetectionBatch([], [], [], [])

        results = self._tracker.update(batch)
        observations: list[TrackObservation] = []

        if len(results) > 0:
            for row in results:
                x1, y1, x2, y2, track_id_val, score, cls_id, idx_val = row[:8]
                track_id = int(track_id_val)
                self._all_track_ids.add(track_id)

                idx = int(idx_val)
                if 0 <= idx < len(detections):
                    class_name = detections[idx].class_name
                else:
                    class_name = "unknown"

                ground_x = float((x1 + x2) / 2.0)
                ground_y = float(y2)
                self._total_observations += 1

                observations.append(
                    TrackObservation(
                        track_id=track_id,
                        frame_number=frame_number,
                        timestamp_s=timestamp_s,
                        vehicle_class=class_name,
                        confidence=float(score),
                        x1=float(x1),
                        y1=float(y1),
                        x2=float(x2),
                        y2=float(y2),
                        ground_x=ground_x,
                        ground_y=ground_y,
                        trajectory_status="complete",
                    )
                )

        return observations

    @property
    def metrics(self) -> TrackingMetrics:
        active = len([s for s in getattr(self._tracker, "tracked_stracks", []) if getattr(s, "is_activated", False)])
        return TrackingMetrics(
            total_tracks=len(self._all_track_ids),
            active_tracks=active,
            total_observations=self._total_observations,
            id_switches=None,  # Explicitly unmeasured: true ID switches require ground-truth identities
        )


def evaluate_id_switches(ground_truth_assignments: Sequence[tuple[int, int, int]]) -> int:
    """Evaluate CLEAR MOT identity switches against known ground-truth associations.

    Parameters:
        ground_truth_assignments: Sequence of (frame_number, gt_id, predicted_track_id) tuples.

    Returns:
        The total count of identity switches where a known ground-truth vehicle
        identity changes its assigned predicted tracker ID.
    """
    ordered = sorted(ground_truth_assignments, key=lambda item: (item[0], item[1]))
    last_assigned_track: dict[int, int] = {}
    id_switches = 0

    for _frame, gt_id, predicted_track_id in ordered:
        if gt_id in last_assigned_track:
            if last_assigned_track[gt_id] != predicted_track_id:
                id_switches += 1
                last_assigned_track[gt_id] = predicted_track_id
        else:
            last_assigned_track[gt_id] = predicted_track_id

    return id_switches


def resolve_track_class(
    observations: Sequence[TrackObservation | Any],
    *,
    min_confidence: float = 0.0,
    fallback_class: str = "unknown",
) -> str:
    """Derive a single consensus vehicle class for a track via confidence-weighted voting.

    Preserves raw historical per-frame observations while producing a deterministic,
    track-level classification suitable for downstream civil-engineering volume aggregation.

    Policy:
    - Filters observations where confidence < min_confidence or vehicle_class is empty/fallback.
    - Accumulates total confidence score and observation count per class.
    - Ranks classes deterministically by:
        1. Cumulative confidence score (descending)
        2. Observation count (descending)
        3. Class name (alphabetical ascending, for deterministic tie-breaking)
    - Returns fallback_class if no observations meet the criteria.
    """
    if not observations:
        return fallback_class

    class_scores: dict[str, float] = {}
    class_counts: dict[str, int] = {}

    for obs in observations:
        v_class = getattr(obs, "vehicle_class", None)
        if not v_class or v_class == fallback_class:
            continue
        conf = float(getattr(obs, "confidence", 0.0))
        if conf < min_confidence:
            continue
        class_scores[v_class] = class_scores.get(v_class, 0.0) + conf
        class_counts[v_class] = class_counts.get(v_class, 0) + 1

    if not class_scores:
        return fallback_class

    candidates = sorted(
        class_scores.keys(),
        key=lambda c: (-class_scores[c], -class_counts[c], c),
    )
    return candidates[0]
