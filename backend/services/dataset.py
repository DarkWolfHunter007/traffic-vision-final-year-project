"""Phase 11 active-learning dataset preparation and leakage-safe export service.

Orchestrates approved manual review aggregation, frame selection, duplicate resolution,
group-based split assignment, YOLO image/label export, manifest generation, and leakage auditing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any

import cv2
import numpy as np

from backend.config import canonical_json, config_hash, load_config
from backend.database.connection import database_connection
from backend.database.repository import (
    fetch_approved_manual_reviews,
    fetch_ground_truth_segments,
    fetch_video_by_id,
)
from backend.dataset import (
    DatasetManifest,
    DatasetSample,
    YoloAnnotation,
    assign_split_group_key,
    audit_split_leakage,
    convert_box_to_yolo,
    deduplicate_frame_reviews,
    format_yolo_labels,
    generate_dataset_yaml,
    split_groups_deterministic,
)
from backend.review import ReviewBox, validate_bounding_box
from backend.services.ingestion import current_code_version

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _resolve_paths(
    config: dict[str, Any] | None, repository_root: Path | None
) -> tuple[dict[str, Any], Path, Path]:
    repo_root = repository_root or Path(__file__).resolve().parents[2]
    cfg = config or load_config()
    db_path = Path(cfg["paths"]["database_path"])
    if not db_path.is_absolute():
        db_path = repo_root / db_path
    return cfg, repo_root, db_path


def _extract_frame_image(video_path: Path, frame_number: int, output_image_path: Path) -> bool:
    """Extract a specific frame from a video file and save it as an image."""
    output_image_path.parent.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Unable to open video file for frame extraction: {video_path}")
    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ret, frame = cap.read()
        if not ret or frame is None:
            raise RuntimeError(f"Failed to read frame {frame_number} from video {video_path}")
        success = cv2.imwrite(str(output_image_path), frame)
        if not success:
            raise RuntimeError(f"Failed to write image file to {output_image_path}")
        return True
    finally:
        cap.release()


def build_active_learning_dataset(
    output_dir: Path | str | None = None,
    dataset_version: str | None = None,
    run_id: str | None = None,
    video_id: str | None = None,
    split_ratios: Mapping[str, float] | None = None,
    split_strategy: str | None = None,
    time_block_duration_s: float | None = None,
    seed: int | None = None,
    min_frame_interval_s: float | None = None,
    export_images: bool | None = None,
    config: dict[str, Any] | None = None,
    repository_root: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Build a versioned, leakage-safe active-learning dataset from approved human corrections.

    Strict Invariants:
    1. Only approved manual reviews ('approved') are included.
    2. Group-based splitting prevents frame-level leakage across splits.
    3. Ground-truth evaluation clips NEVER enter the 'train' split.
    4. Human-reviewed corrections NEVER enter the 'test' split.
    5. Reproducibility: Deterministic seeded grouping and split assignment.
    """
    cfg, repo_root, db_path = _resolve_paths(config, repository_root)
    al_cfg = cfg.get("active_learning", {})

    target_version = dataset_version or str(al_cfg.get("default_version", "v1"))
    raw_out_dir = output_dir or al_cfg.get("output_dir", "data/processed/datasets")
    out_dir_path = Path(raw_out_dir)
    if not out_dir_path.is_absolute():
        out_dir_path = repo_root / out_dir_path
    dataset_root = out_dir_path / target_version

    strat = split_strategy or str(al_cfg.get("split_strategy", "time_block"))
    block_dur = (
        float(time_block_duration_s)
        if time_block_duration_s is not None
        else float(al_cfg.get("time_block_duration_s", 300.0))
    )
    ratios = split_ratios or al_cfg.get("split_ratios", {"train": 0.8, "val": 0.2, "test": 0.0})
    split_seed = int(seed) if seed is not None else int(al_cfg.get("seed", 42))
    dup_policy = str(al_cfg.get("duplicate_policy", "latest_review"))
    class_mapping: dict[str, int] = dict(al_cfg.get("class_mapping", {}))
    min_gap = (
        float(min_frame_interval_s)
        if min_frame_interval_s is not None
        else float(al_cfg.get("min_frame_interval_s", 0.0))
    )
    do_export_images = (
        bool(export_images)
        if export_images is not None
        else bool(al_cfg.get("export_images", True))
    )

    def _execute(conn: sqlite3.Connection) -> dict[str, Any]:
        # 1. Fetch approved manual reviews
        reviews = fetch_approved_manual_reviews(conn, run_id=run_id, video_id=video_id)
        if not reviews:
            raise ValueError(
                f"No approved manual reviews found matching criteria (run_id={run_id}, video_id={video_id})"
            )

        # 2. Fetch ground-truth segments and videos to prevent leakage into train
        gt_segments = fetch_ground_truth_segments(conn)
        gt_video_ids = {row["video_id"] for row in gt_segments}

        # 3. Cache video metadata
        unique_video_ids = sorted({r["video_id"] for r in reviews})
        video_cache: dict[str, dict[str, Any]] = {}
        for vid in unique_video_ids:
            v_row = fetch_video_by_id(conn, vid)
            if v_row is None:
                raise ValueError(f"Video '{vid}' referenced in manual reviews was not found in videos table")
            v_path = Path(v_row["path"])
            if not v_path.is_absolute():
                v_path = repo_root / v_path
            video_cache[vid] = {
                "video_id": vid,
                "path": v_path,
                "sha256": v_row["sha256"],
                "width": int(v_row["width"]),
                "height": int(v_row["height"]),
            }

        # 4. Group reviews by frame (video_id, frame_number)
        reviews_by_frame: dict[tuple[str, int], list[Any]] = {}
        for r in reviews:
            key = (r["video_id"], int(r["frame_number"]))
            reviews_by_frame.setdefault(key, []).append(r)

        # 5. Sort frames and apply temporal sampling stride if configured
        sorted_frame_keys = sorted(
            reviews_by_frame.keys(),
            key=lambda k: (k[0], reviews_by_frame[k][0]["timestamp_s"], k[1]),
        )

        selected_frame_keys: list[tuple[str, int]] = []
        last_ts_by_video: dict[str, float] = {}
        for key in sorted_frame_keys:
            vid, fn = key
            frame_revs = reviews_by_frame[key]
            ts = float(frame_revs[0]["timestamp_s"])
            if min_gap > 0 and vid in last_ts_by_video:
                if (ts - last_ts_by_video[vid]) < min_gap:
                    continue
            selected_frame_keys.append(key)
            last_ts_by_video[vid] = ts

        # 6. Build frame-level groups and determine ground-truth status
        frame_items: list[dict[str, Any]] = []
        gt_group_ids: set[str] = set()

        for key in selected_frame_keys:
            vid, fn = key
            frame_revs = reviews_by_frame[key]
            ts = float(frame_revs[0]["timestamp_s"])
            group_key = assign_split_group_key(
                video_id=vid,
                timestamp_s=ts,
                strategy=strat,
                time_block_duration_s=block_dur,
            )

            # Check if frame falls inside a ground-truth evaluation clip
            is_gt_frame = False
            for gt_seg in gt_segments:
                if gt_seg["video_id"] == vid:
                    start_s = float(gt_seg["start_s"])
                    end_s = float(gt_seg["end_s"])
                    if start_s <= ts <= end_s:
                        is_gt_frame = True
                        break

            if is_gt_frame:
                gt_group_ids.add(group_key)

            deduped_revs = deduplicate_frame_reviews(frame_revs, policy=dup_policy)
            frame_items.append({
                "video_id": vid,
                "frame_number": fn,
                "timestamp_s": ts,
                "group_key": group_key,
                "is_gt_frame": is_gt_frame,
                "reviews": deduped_revs,
            })

        # 7. Deterministic group-based split assignment
        all_group_keys = [item["group_key"] for item in frame_items]
        group_split_map = split_groups_deterministic(
            group_ids=all_group_keys,
            split_ratios=ratios,
            seed=split_seed,
            ground_truth_group_ids=gt_group_ids,
            is_corrected_sample=True,
        )

        # 8. Create filesystem directory structure
        for sp in ("train", "val", "test"):
            (dataset_root / "images" / sp).mkdir(parents=True, exist_ok=True)
            (dataset_root / "labels" / sp).mkdir(parents=True, exist_ok=True)

        # 9. Process each frame: convert boxes, export labels & images
        exported_samples: list[DatasetSample] = []
        class_distribution: dict[str, int] = {c: 0 for c in class_mapping}
        splits_present_set: set[str] = set()

        for item in frame_items:
            vid = item["video_id"]
            fn = item["frame_number"]
            ts = item["timestamp_s"]
            grp = item["group_key"]
            split = group_split_map[grp]
            splits_present_set.add(split)
            v_meta = video_cache[vid]
            fw, fh = v_meta["width"], v_meta["height"]

            sample_id = f"{vid}_f{fn:06d}"
            annotations: list[YoloAnnotation] = []
            review_ids: list[str] = []
            reviewers: list[str] = []
            reviewed_ats: list[str] = []
            sample_run_id = item["reviews"][0]["run_id"]

            for rev in item["reviews"]:
                review_ids.append(str(rev["review_id"]))
                reviewers.append(str(rev["reviewer"]))
                reviewed_ats.append(str(rev["reviewed_at"]))

                # Resolve effective vehicle class
                eff_class = rev["corrected_class"] or rev["original_class"]
                if not eff_class or eff_class not in class_mapping:
                    raise ValueError(
                        f"Vehicle class '{eff_class}' from review '{rev['review_id']}' is not in configured class_mapping: {list(class_mapping.keys())}"
                    )
                cid = class_mapping[eff_class]
                class_distribution[eff_class] += 1

                # Resolve effective bounding box
                raw_bbox = rev["corrected_bbox_json"] or rev["original_bbox_json"]
                if not raw_bbox:
                    raise ValueError(f"No bounding box available in review '{rev['review_id']}'")
                box_dict = json.loads(raw_bbox) if isinstance(raw_bbox, str) else dict(raw_bbox)
                validated_box = validate_bounding_box(box_dict, frame_width=fw, frame_height=fh)

                # Convert to normalized YOLO coordinates
                yolo_ann = YoloAnnotation.from_pixel_box(
                    box=validated_box,
                    frame_width=fw,
                    frame_height=fh,
                    class_id=cid,
                )
                annotations.append(yolo_ann)

            # Write label file
            label_rel = f"labels/{split}/{sample_id}.txt"
            label_abs = dataset_root / label_rel
            label_content = format_yolo_labels(annotations)
            label_abs.write_text(label_content, encoding="utf-8")

            # Extract & save image file if requested
            image_rel = f"images/{split}/{sample_id}.jpg"
            image_abs = dataset_root / image_rel
            if do_export_images:
                v_path = v_meta["path"]
                if not v_path.exists():
                    raise FileNotFoundError(f"Source video file not found on disk: {v_path}")
                _extract_frame_image(v_path, fn, image_abs)

            sample = DatasetSample(
                sample_id=sample_id,
                video_id=vid,
                source_video_sha256=v_meta["sha256"],
                run_id=sample_run_id,
                frame_number=fn,
                timestamp_s=ts,
                split=split,
                split_group=grp,
                annotations=annotations,
                review_ids=review_ids,
                reviewers=reviewers,
                reviewed_at=reviewed_ats,
                is_ground_truth_clip=item["is_gt_frame"],
                image_rel_path=image_rel if do_export_images else None,
                label_rel_path=label_rel,
            )
            exported_samples.append(sample)

        # 10. Generate dataset.yaml
        splits_present = sorted(splits_present_set)
        yaml_content = generate_dataset_yaml(
            dataset_dir=dataset_root,
            class_mapping=class_mapping,
            splits_present=splits_present,
        )
        yaml_path = dataset_root / "dataset.yaml"
        yaml_path.write_text(yaml_content, encoding="utf-8")

        # 11. Compile group breakdown by split
        groups_by_split: dict[str, list[str]] = {}
        for grp, sp in sorted(group_split_map.items()):
            groups_by_split.setdefault(sp, []).append(grp)

        split_counts: dict[str, int] = {}
        for sp in ("train", "val", "test"):
            split_counts[sp] = sum(1 for s in exported_samples if s.split == sp)

        # 12. Write manifest.json
        c_hash = config_hash(cfg)
        git_sha = current_code_version(repo_root)
        manifest = DatasetManifest(
            dataset_version=target_version,
            created_at=_utc_now_iso(),
            config_hash=c_hash,
            code_version=git_sha,
            description="Phase 11 active-learning dataset generated from approved human corrections",
            origin_description="Manual reviews approved via Phase 10 human-in-the-loop review interface",
            class_mapping=class_mapping,
            split_ratios=dict(ratios),
            split_counts=split_counts,
            total_samples=len(exported_samples),
            total_boxes=sum(len(s.annotations) for s in exported_samples),
            groups_by_split=groups_by_split,
            samples=[s.to_dict() for s in exported_samples],
        )
        manifest_path = dataset_root / "manifest.json"
        manifest_path.write_text(manifest.to_json(), encoding="utf-8")

        # 13. Audit leakage
        leakage_report = audit_split_leakage(
            samples=exported_samples,
            ground_truth_video_ids=list(gt_video_ids),
        )
        if not leakage_report["is_leakage_safe"]:
            logger.error("Dataset leakage audit failed: %s", leakage_report)
            raise RuntimeError(f"Split leakage safety audit failed: {leakage_report}")

        return {
            "dataset_version": target_version,
            "dataset_dir": str(dataset_root),
            "manifest_path": str(manifest_path),
            "yaml_path": str(yaml_path),
            "total_samples": len(exported_samples),
            "total_boxes": manifest.total_boxes,
            "split_counts": split_counts,
            "class_distribution": class_distribution,
            "leakage_audit": leakage_report,
        }

    if connection is not None:
        return _execute(connection)

    with database_connection(db_path) as conn:
        return _execute(conn)


def get_dataset_manifest(dataset_path: Path | str) -> dict[str, Any]:
    """Load and parse manifest.json from a dataset directory or manifest file path."""
    p = Path(dataset_path)
    if p.is_dir():
        p = p / "manifest.json"
    if not p.is_file():
        raise FileNotFoundError(f"Dataset manifest file not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def audit_dataset_leakage_from_path(
    manifest_or_dataset_path: Path | str | dict[str, Any],
    ground_truth_video_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Audit an existing dataset or manifest for data leakage safety."""
    if isinstance(manifest_or_dataset_path, dict):
        manifest_data = manifest_or_dataset_path
    else:
        manifest_data = get_dataset_manifest(manifest_or_dataset_path)

    samples = manifest_data.get("samples", [])
    return audit_split_leakage(
        samples=samples,
        ground_truth_video_ids=ground_truth_video_ids,
    )
