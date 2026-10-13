"""Phase 11 pure logic: YOLO dataset formatting, leakage-safe group splitting, and manifests.

Provides deterministic coordinate transformations, group-based train/val/test splitting,
ground-truth evaluation clip safety enforcement, duplicate resolution, and manifest structures.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from backend.review import ReviewBox, validate_bounding_box


@dataclass(frozen=True)
class YoloAnnotation:
    """Canonical YOLO bounding box format with normalized coordinates in [0.0, 1.0]."""

    class_id: int
    x_center: float
    y_center: float
    width: float
    height: float

    def to_yolo_line(self, precision: int = 6) -> str:
        """Format as standard YOLO label line: <class_id> <x_center> <y_center> <width> <height>."""
        return (
            f"{self.class_id} "
            f"{self.x_center:.{precision}f} "
            f"{self.y_center:.{precision}f} "
            f"{self.width:.{precision}f} "
            f"{self.height:.{precision}f}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "class_id": self.class_id,
            "x_center": round(self.x_center, 6),
            "y_center": round(self.y_center, 6),
            "width": round(self.width, 6),
            "height": round(self.height, 6),
        }

    @classmethod
    def from_pixel_box(
        cls,
        box: ReviewBox | Mapping[str, Any] | Sequence[float],
        frame_width: int | float,
        frame_height: int | float,
        class_id: int,
    ) -> YoloAnnotation:
        """Convert pixel bounding box coordinates to a normalized YoloAnnotation."""
        if isinstance(box, ReviewBox):
            x1, y1, x2, y2 = box.x1, box.y1, box.x2, box.y2
        elif isinstance(box, Mapping):
            x1, y1, x2, y2 = float(box["x1"]), float(box["y1"]), float(box["x2"]), float(box["y2"])
        elif isinstance(box, (list, tuple)) and len(box) == 4:
            x1, y1, x2, y2 = float(box[0]), float(box[1]), float(box[2]), float(box[3])
        else:
            raise ValueError(f"Unsupported bounding box type for YOLO conversion: {type(box)}")

        xc, yc, w, h = convert_box_to_yolo(x1, y1, x2, y2, frame_width, frame_height)
        return cls(class_id=int(class_id), x_center=xc, y_center=yc, width=w, height=h)


@dataclass(frozen=True)
class DatasetSample:
    """An exported frame sample retaining complete source video/run/review provenance."""

    sample_id: str
    video_id: str
    source_video_sha256: str
    run_id: str
    frame_number: int
    timestamp_s: float
    split: str  # 'train' | 'val' | 'test'
    split_group: str
    annotations: list[YoloAnnotation] = field(default_factory=list)
    review_ids: list[str] = field(default_factory=list)
    reviewers: list[str] = field(default_factory=list)
    reviewed_at: list[str] = field(default_factory=list)
    is_ground_truth_clip: bool = False
    image_rel_path: str | None = None
    label_rel_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "video_id": self.video_id,
            "source_video_sha256": self.source_video_sha256,
            "run_id": self.run_id,
            "frame_number": self.frame_number,
            "timestamp_s": round(self.timestamp_s, 4),
            "split": self.split,
            "split_group": self.split_group,
            "annotations": [a.to_dict() for a in self.annotations],
            "review_ids": list(self.review_ids),
            "reviewers": list(self.reviewers),
            "reviewed_at": list(self.reviewed_at),
            "is_ground_truth_clip": self.is_ground_truth_clip,
            "image_rel_path": self.image_rel_path,
            "label_rel_path": self.label_rel_path,
        }


@dataclass(frozen=True)
class DatasetManifest:
    """Full dataset manifest preserving lineage, group splitting, and per-sample provenance."""

    dataset_version: str
    created_at: str
    config_hash: str
    code_version: str
    description: str
    origin_description: str
    class_mapping: dict[str, int]
    split_ratios: dict[str, float]
    split_counts: dict[str, int]
    total_samples: int
    total_boxes: int
    groups_by_split: dict[str, list[str]]
    samples: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_version": self.dataset_version,
            "created_at": self.created_at,
            "config_hash": self.config_hash,
            "code_version": self.code_version,
            "description": self.description,
            "origin_description": self.origin_description,
            "class_mapping": dict(self.class_mapping),
            "split_ratios": dict(self.split_ratios),
            "split_counts": dict(self.split_counts),
            "total_samples": self.total_samples,
            "total_boxes": self.total_boxes,
            "groups_by_split": {k: list(v) for k, v in self.groups_by_split.items()},
            "samples": self.samples,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


def convert_box_to_yolo(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    frame_width: int | float,
    frame_height: int | float,
) -> tuple[float, float, float, float]:
    """Convert pixel bounding box coordinates to normalized YOLO [x_center, y_center, width, height].

    Validates numeric finiteness, non-inversion, non-zero dimensions, and bounds within frame.
    Coordinates are normalized and clamped to [0.0, 1.0].
    """
    for val, name in ((x1, "x1"), (y1, "y1"), (x2, "x2"), (y2, "y2")):
        if math.isnan(val) or math.isinf(val):
            raise ValueError(f"Coordinate {name} must be a finite number, got {val}")

    if frame_width <= 0:
        raise ValueError(f"frame_width must be positive, got {frame_width}")
    if frame_height <= 0:
        raise ValueError(f"frame_height must be positive, got {frame_height}")

    if x1 >= x2:
        raise ValueError(f"Bounding box x1 ({x1}) must be strictly less than x2 ({x2})")
    if y1 >= y2:
        raise ValueError(f"Bounding box y1 ({y1}) must be strictly less than y2 ({y2})")

    # Clamp coordinates to frame boundary to prevent negative or > 1.0 coords
    cx1 = max(0.0, min(float(x1), float(frame_width)))
    cy1 = max(0.0, min(float(y1), float(frame_height)))
    cx2 = max(0.0, min(float(x2), float(frame_width)))
    cy2 = max(0.0, min(float(y2), float(frame_height)))

    box_w = cx2 - cx1
    box_h = cy2 - cy1
    if box_w <= 0.0 or box_h <= 0.0:
        raise ValueError(f"Clamped bounding box area is zero for box [{x1}, {y1}, {x2}, {y2}]")

    x_center = (cx1 + cx2) / (2.0 * float(frame_width))
    y_center = (cy1 + cy2) / (2.0 * float(frame_height))
    norm_w = box_w / float(frame_width)
    norm_h = box_h / float(frame_height)

    # Final sanity clamp to [0.0, 1.0]
    x_center = max(0.0, min(1.0, x_center))
    y_center = max(0.0, min(1.0, y_center))
    norm_w = max(0.0, min(1.0, norm_w))
    norm_h = max(0.0, min(1.0, norm_h))

    return x_center, y_center, norm_w, norm_h


def format_yolo_labels(annotations: Sequence[YoloAnnotation]) -> str:
    """Format sequence of YoloAnnotation objects into newline-separated YOLO text file content."""
    if not annotations:
        return ""
    lines = [ann.to_yolo_line() for ann in annotations]
    return "\n".join(lines) + "\n"


def parse_yolo_label_line(line: str) -> YoloAnnotation:
    """Parse a single YOLO label file line into a YoloAnnotation."""
    parts = line.strip().split()
    if len(parts) != 5:
        raise ValueError(f"YOLO label line must contain exactly 5 space-separated values, got: '{line}'")
    class_id = int(parts[0])
    xc = float(parts[1])
    yc = float(parts[2])
    w = float(parts[3])
    h = float(parts[4])
    return YoloAnnotation(class_id=class_id, x_center=xc, y_center=yc, width=w, height=h)


def assign_split_group_key(
    video_id: str,
    timestamp_s: float,
    strategy: str = "time_block",
    time_block_duration_s: float = 300.0,
) -> str:
    """Derive deterministic group identifier to prevent split leakage across frames."""
    if strategy == "video":
        return f"vid_{video_id}"
    elif strategy == "time_block":
        if time_block_duration_s <= 0:
            raise ValueError(f"time_block_duration_s must be positive, got {time_block_duration_s}")
        block_idx = int(timestamp_s // time_block_duration_s)
        return f"vid_{video_id}_blk_{block_idx:04d}"
    else:
        raise ValueError(f"Unsupported split_strategy: '{strategy}'. Must be 'video' or 'time_block'.")


def split_groups_deterministic(
    group_ids: Sequence[str],
    split_ratios: Mapping[str, float] | None = None,
    seed: int = 42,
    ground_truth_group_ids: Sequence[str] | set[str] | None = None,
    is_corrected_sample: bool = True,
) -> dict[str, str]:
    """Deterministically assign group identifiers to splits ('train', 'val', 'test').

    Invariants:
    1. Group-level atomicity: Every member of group_id receives the same split.
    2. Ground-truth clip exclusion: Groups identified in ground_truth_group_ids MUST NEVER enter 'train'.
    3. Corrected-sample safety: Human-corrected samples MUST NEVER enter 'test'.
    4. Determinism: Given same groups, seed, and ratios, output is 100% reproducible.
    """
    if split_ratios is None:
        ratios = {"train": 0.8, "val": 0.2, "test": 0.0}
    else:
        ratios = dict(split_ratios)

    gt_groups = set(ground_truth_group_ids) if ground_truth_group_ids else set()
    unique_groups = sorted(set(group_ids))
    if not unique_groups:
        return {}

    # If corrected samples, test ratio is forced to 0.0 to prevent contamination of test set
    train_weight = float(ratios.get("train", 0.0))
    val_weight = float(ratios.get("val", 0.0))
    test_weight = 0.0 if is_corrected_sample else float(ratios.get("test", 0.0))

    normal_sum = train_weight + val_weight + test_weight
    if normal_sum <= 0:
        # Default fallback to 80/20 train/val
        train_weight, val_weight, test_weight = 0.8, 0.2, 0.0
        normal_sum = 1.0

    p_train = train_weight / normal_sum
    p_val = val_weight / normal_sum

    assignments: dict[str, str] = {}
    for gid in unique_groups:
        # Check ground-truth safety constraint
        if gid in gt_groups:
            # Ground truth must NEVER enter train
            # If val is non-zero, assign to val; otherwise test (if non-corrected), else val
            assignments[gid] = "val"
            continue

        # Deterministic seeded hash for group assignment
        hasher = hashlib.sha256(f"{seed}_{gid}".encode("utf-8"))
        # Use first 8 hex characters as 32-bit unsigned int
        hash_val = int(hasher.hexdigest()[:8], 16) / float(0xFFFFFFFF)

        if hash_val < p_train:
            assignments[gid] = "train"
        elif hash_val < (p_train + p_val):
            assignments[gid] = "val"
        else:
            assignments[gid] = "test" if not is_corrected_sample else "val"

    return assignments


def deduplicate_frame_reviews(
    reviews_for_frame: Sequence[Mapping[str, Any] | Any],
    policy: str = "latest_review",
) -> list[Mapping[str, Any] | Any]:
    """Resolve duplicate reviews for the same video frame according to policy.

    In 'latest_review' policy:
    If multiple review records target the same track_id or detection_id on the same frame,
    the review with the latest 'reviewed_at' timestamp is retained.
    """
    if policy == "keep_all" or len(reviews_for_frame) <= 1:
        return list(reviews_for_frame)

    if policy != "latest_review":
        raise ValueError(f"Unsupported duplicate_policy: '{policy}'. Must be 'latest_review' or 'keep_all'.")

    # Group by object identity: track_id if present, else detection_id if present, else review_id
    by_target: dict[str, list[Any]] = {}
    for rev in reviews_for_frame:
        track_id = rev["track_id"] if rev["track_id"] is not None else None
        det_id = rev["detection_id"] if rev["detection_id"] is not None else None

        if track_id is not None:
            key = f"track_{track_id}"
        elif det_id is not None:
            key = f"det_{det_id}"
        else:
            key = f"rev_{rev['review_id']}"

        by_target.setdefault(key, []).append(rev)

    deduped = []
    for key, items in by_target.items():
        if len(items) == 1:
            deduped.append(items[0])
        else:
            # Sort by reviewed_at descending and take latest
            sorted_items = sorted(
                items,
                key=lambda x: str(x["reviewed_at"] or ""),
                reverse=True,
            )
            deduped.append(sorted_items[0])

    return deduped


def audit_split_leakage(
    samples: Sequence[Mapping[str, Any] | DatasetSample],
    ground_truth_video_ids: Sequence[str] | None = None,
    ground_truth_segment_bounds: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Audit exported samples to ensure strict data leakage safety.

    Validates:
    1. Group atomicity: No split_group has samples in multiple splits.
    2. Ground-truth exclusion: No ground-truth clip/segment frame is in 'train'.
    3. Corrected sample safety: No human-reviewed correction is in 'test'.
    """
    gt_vids = set(ground_truth_video_ids) if ground_truth_video_ids else set()
    gt_bounds = list(ground_truth_segment_bounds) if ground_truth_segment_bounds else []

    group_to_splits: dict[str, set[str]] = {}
    train_gt_violations: list[dict[str, Any]] = []
    test_corrected_violations: list[dict[str, Any]] = []

    for s in samples:
        s_dict = s.to_dict() if isinstance(s, DatasetSample) else dict(s)
        split = s_dict["split"]
        group = s_dict["split_group"]
        vid = s_dict["video_id"]
        ts = float(s_dict["timestamp_s"])
        fn = int(s_dict["frame_number"])

        group_to_splits.setdefault(group, set()).add(split)

        # Check ground-truth in train
        is_gt = s_dict.get("is_ground_truth_clip", False) or (vid in gt_vids)
        if not is_gt and gt_bounds:
            for bound in gt_bounds:
                if bound.get("video_id") == vid:
                    start_s = float(bound.get("start_s", 0.0))
                    end_s = float(bound.get("end_s", float("inf")))
                    if start_s <= ts <= end_s:
                        is_gt = True
                        break

        if is_gt and split == "train":
            train_gt_violations.append({
                "sample_id": s_dict.get("sample_id"),
                "video_id": vid,
                "frame_number": fn,
                "timestamp_s": ts,
                "split": split,
            })

        # Check corrected sample in test
        if s_dict.get("review_ids") and split == "test":
            test_corrected_violations.append({
                "sample_id": s_dict.get("sample_id"),
                "video_id": vid,
                "frame_number": fn,
                "split": split,
            })

    # Group leakage: any group mapped to > 1 split
    leaked_groups = {g: sorted(splits) for g, splits in group_to_splits.items() if len(splits) > 1}

    is_safe = (
        len(leaked_groups) == 0
        and len(train_gt_violations) == 0
        and len(test_corrected_violations) == 0
    )

    return {
        "is_leakage_safe": is_safe,
        "group_leakage_detected": len(leaked_groups) > 0,
        "leaked_groups": leaked_groups,
        "ground_truth_in_train_count": len(train_gt_violations),
        "ground_truth_in_train_violations": train_gt_violations,
        "corrected_in_test_count": len(test_corrected_violations),
        "corrected_in_test_violations": test_corrected_violations,
        "total_samples_audited": len(samples),
        "total_groups_audited": len(group_to_splits),
    }


def generate_dataset_yaml(
    dataset_dir: str | Path,
    class_mapping: Mapping[str, int],
    splits_present: Sequence[str] = ("train", "val"),
) -> str:
    """Generate Ultralytics YOLO dataset.yaml string content."""
    # Build names mapping sorted by integer class_id
    sorted_classes = sorted(class_mapping.items(), key=lambda kv: kv[1])

    lines = [
        f"# Traffic Vision YOLO dataset specification",
        f"path: {str(Path(dataset_dir).as_posix())}",
    ]
    if "train" in splits_present:
        lines.append("train: images/train")
    if "val" in splits_present:
        lines.append("val: images/val")
    if "test" in splits_present:
        lines.append("test: images/test")

    lines.append("")
    lines.append("names:")
    for name, cid in sorted_classes:
        lines.append(f"  {cid}: {name}")

    return "\n".join(lines) + "\n"
