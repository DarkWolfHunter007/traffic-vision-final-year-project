"""Phase 11 unit tests for pure dataset logic, coordinate transformations, and splitting.

All fixtures in this module are synthetic software fixtures, explicitly labelled as such.
No real-world research measurements or calibration points are fabricated.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from backend.config import ConfigError, load_config
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
    parse_yolo_label_line,
    split_groups_deterministic,
)
from backend.review import ReviewBox


def test_tp11_01_box_to_yolo_conversion_accuracy() -> None:
    """TP11-01: Pixel coordinates convert accurately to normalized [xc, yc, w, h] in [0, 1]."""
    # Test box on 640x480 image
    # Box: x1=64, y1=48, x2=192, y2=144 -> w=128, h=96, xc=128, yc=96
    # Normalized: xc=128/640=0.2, yc=96/480=0.2, w=128/640=0.2, h=96/480=0.2
    xc, yc, w, h = convert_box_to_yolo(64, 48, 192, 144, 640, 480)
    assert pytest.approx(xc, rel=1e-5) == 0.2
    assert pytest.approx(yc, rel=1e-5) == 0.2
    assert pytest.approx(w, rel=1e-5) == 0.2
    assert pytest.approx(h, rel=1e-5) == 0.2

    # YoloAnnotation from ReviewBox
    box = ReviewBox(x1=100.0, y1=100.0, x2=300.0, y2=200.0)
    ann = YoloAnnotation.from_pixel_box(box, frame_width=1000, frame_height=500, class_id=1)
    # xc = (100+300)/2 / 1000 = 0.2
    # yc = (100+200)/2 / 500 = 0.3
    # w = 200 / 1000 = 0.2
    # h = 100 / 500 = 0.2
    assert ann.class_id == 1
    assert pytest.approx(ann.x_center, rel=1e-5) == 0.2
    assert pytest.approx(ann.y_center, rel=1e-5) == 0.3
    assert pytest.approx(ann.width, rel=1e-5) == 0.2
    assert pytest.approx(ann.height, rel=1e-5) == 0.2


def test_tp11_01_box_to_yolo_boundary_clamping_and_validation() -> None:
    """TP11-01 edge cases: Non-inversion, positive frame dimensions, and clamping."""
    # Inverted coordinates must raise ValueError
    with pytest.raises(ValueError, match="strictly less than x2"):
        convert_box_to_yolo(200, 50, 100, 150, 640, 480)

    with pytest.raises(ValueError, match="strictly less than y2"):
        convert_box_to_yolo(50, 200, 150, 100, 640, 480)

    # Invalid frame dimension
    with pytest.raises(ValueError, match="frame_width must be positive"):
        convert_box_to_yolo(50, 50, 150, 150, 0, 480)

    # Finite numbers
    with pytest.raises(ValueError, match="must be a finite number"):
        convert_box_to_yolo(float("nan"), 50, 150, 150, 640, 480)


def test_tp11_02_yolo_label_formatting_and_parsing() -> None:
    """TP11-02: Multiple annotations per frame format to standard YOLO text lines."""
    ann1 = YoloAnnotation(class_id=0, x_center=0.25, y_center=0.35, width=0.10, height=0.20)
    ann2 = YoloAnnotation(class_id=4, x_center=0.75, y_center=0.85, width=0.05, height=0.15)

    label_text = format_yolo_labels([ann1, ann2])
    lines = [line.strip() for line in label_text.strip().split("\n")]
    assert len(lines) == 2
    assert lines[0] == "0 0.250000 0.350000 0.100000 0.200000"
    assert lines[1] == "4 0.750000 0.850000 0.050000 0.150000"

    # Test roundtrip parsing
    parsed1 = parse_yolo_label_line(lines[0])
    assert parsed1.class_id == 0
    assert pytest.approx(parsed1.x_center) == 0.25
    assert pytest.approx(parsed1.width) == 0.10

    # Empty list produces empty string
    assert format_yolo_labels([]) == ""


def test_tp11_05_group_based_split_by_video_leakage_safety() -> None:
    """TP11-05: Frames from the same video are grouped together without cross-split video leakage."""
    video_a_frames = [
        DatasetSample(
            sample_id=f"vid_A_f{i}",
            video_id="vid_A",
            source_video_sha256="sha_A",
            run_id="run_1",
            frame_number=i,
            timestamp_s=i * 1.0,
            split="train",
            split_group="vid_A",
        )
        for i in range(10)
    ]
    video_b_frames = [
        DatasetSample(
            sample_id=f"vid_B_f{i}",
            video_id="vid_B",
            source_video_sha256="sha_B",
            run_id="run_1",
            frame_number=i,
            timestamp_s=i * 1.0,
            split="val",
            split_group="vid_B",
        )
        for i in range(10)
    ]

    all_samples = video_a_frames + video_b_frames
    audit = audit_split_leakage(all_samples)
    assert audit["is_leakage_safe"] is True
    assert audit["group_leakage_detected"] is False

    # Simulate group leakage: Assigning some frames of vid_A to 'val'
    leaked_samples = list(video_a_frames)
    leaked_samples[3] = DatasetSample(
        sample_id="vid_A_f3",
        video_id="vid_A",
        source_video_sha256="sha_A",
        run_id="run_1",
        frame_number=3,
        timestamp_s=3.0,
        split="val",  # LEAK!
        split_group="vid_A",
    )
    audit_leaked = audit_split_leakage(leaked_samples)
    assert audit_leaked["is_leakage_safe"] is False
    assert audit_leaked["group_leakage_detected"] is True
    assert "vid_A" in audit_leaked["leaked_groups"]


def test_tp11_06_group_based_split_by_time_block() -> None:
    """TP11-06: Frames within the same contiguous time block share the same group and split."""
    # Video duration 600s, block duration 300s -> 2 blocks (0-300s, 300-600s)
    group_0 = assign_split_group_key("vid_1", 10.0, strategy="time_block", time_block_duration_s=300.0)
    group_1 = assign_split_group_key("vid_1", 299.9, strategy="time_block", time_block_duration_s=300.0)
    group_2 = assign_split_group_key("vid_1", 300.1, strategy="time_block", time_block_duration_s=300.0)

    assert group_0 == group_1  # same 300s block
    assert group_0 != group_2  # different block
    assert group_0 == "vid_vid_1_blk_0000"
    assert group_2 == "vid_vid_1_blk_0001"


def test_tp11_07_deterministic_seeded_splitting() -> None:
    """TP11-07: Seeded group splitting produces 100% deterministic, reproducible split assignments."""
    groups = [f"group_{i:03d}" for i in range(50)]
    ratios = {"train": 0.8, "val": 0.2, "test": 0.0}

    split_1 = split_groups_deterministic(groups, split_ratios=ratios, seed=42)
    split_2 = split_groups_deterministic(groups, split_ratios=ratios, seed=42)
    assert split_1 == split_2

    # Different seed produces different distribution
    split_diff_seed = split_groups_deterministic(groups, split_ratios=ratios, seed=9999)
    # Check that at least some groups differ between different seeds
    differences = [g for g in groups if split_1[g] != split_diff_seed[g]]
    assert len(differences) > 0


def test_tp11_08_ground_truth_clip_training_exclusion() -> None:
    """TP11-08: Ground-truth evaluation clip groups are strictly forbidden from entering 'train'."""
    groups = ["gt_eval_clip_1", "regular_group_1", "regular_group_2", "gt_eval_clip_2"]
    gt_groups = {"gt_eval_clip_1", "gt_eval_clip_2"}
    ratios = {"train": 0.99, "val": 0.01, "test": 0.0}

    assignments = split_groups_deterministic(
        groups,
        split_ratios=ratios,
        seed=1,
        ground_truth_group_ids=gt_groups,
    )

    # Even with 99% train weight, GT clips MUST NEVER be 'train'
    assert assignments["gt_eval_clip_1"] != "train"
    assert assignments["gt_eval_clip_2"] != "train"
    assert assignments["gt_eval_clip_1"] == "val"
    assert assignments["gt_eval_clip_2"] == "val"

    # Audit function detects any GT frame in train
    sample = DatasetSample(
        sample_id="gt_sample_1",
        video_id="vid_gt",
        source_video_sha256="sha_gt",
        run_id="run_1",
        frame_number=10,
        timestamp_s=5.0,
        split="train",  # VIOLATION
        split_group="gt_group",
        is_ground_truth_clip=True,
    )
    audit = audit_split_leakage([sample])
    assert audit["is_leakage_safe"] is False
    assert audit["ground_truth_in_train_count"] == 1


def test_tp11_09_corrected_sample_test_split_exclusion() -> None:
    """TP11-09: Corrected manual review samples are never assigned to the 'test' split."""
    groups = [f"group_{i}" for i in range(30)]
    # Requesting 50% test split
    ratios = {"train": 0.3, "val": 0.2, "test": 0.5}

    # is_corrected_sample=True forces test_weight to 0.0
    assignments = split_groups_deterministic(
        groups,
        split_ratios=ratios,
        seed=42,
        is_corrected_sample=True,
    )
    for g, sp in assignments.items():
        assert sp in ("train", "val")
        assert sp != "test"

    # Audit catches corrected sample placed in test
    sample = DatasetSample(
        sample_id="corr_sample_1",
        video_id="vid_1",
        source_video_sha256="sha_1",
        run_id="run_1",
        frame_number=10,
        timestamp_s=1.0,
        split="test",  # VIOLATION
        split_group="group_1",
        review_ids=["rev_1"],
    )
    audit = audit_split_leakage([sample])
    assert audit["is_leakage_safe"] is False
    assert audit["corrected_in_test_count"] == 1


def test_tp11_10_duplicate_review_handling() -> None:
    """TP11-10: Multiple reviews for the same frame are handled according to duplicate policy."""
    rev_earlier = {
        "review_id": "rev_01",
        "track_id": 42,
        "detection_id": None,
        "reviewed_at": "2026-10-14T01:00:00Z",
        "corrected_class": "car",
    }
    rev_later = {
        "review_id": "rev_02",
        "track_id": 42,
        "detection_id": None,
        "reviewed_at": "2026-10-14T02:00:00Z",
        "corrected_class": "bus",
    }
    rev_other_track = {
        "review_id": "rev_03",
        "track_id": 99,
        "detection_id": None,
        "reviewed_at": "2026-10-14T01:30:00Z",
        "corrected_class": "motorcycle",
    }

    # latest_review policy should retain rev_later for track 42, plus rev_other_track
    deduped = deduplicate_frame_reviews(
        [rev_earlier, rev_later, rev_other_track],
        policy="latest_review",
    )
    assert len(deduped) == 2
    deduped_ids = {r["review_id"] for r in deduped}
    assert "rev_02" in deduped_ids
    assert "rev_03" in deduped_ids
    assert "rev_01" not in deduped_ids

    # keep_all policy preserves all
    all_revs = deduplicate_frame_reviews(
        [rev_earlier, rev_later, rev_other_track],
        policy="keep_all",
    )
    assert len(all_revs) == 3


def test_tp11_12_dataset_yaml_generation() -> None:
    """TP11-12: generate_dataset_yaml produces standard YOLO format configuration."""
    class_map = {"car": 0, "bus": 1, "auto_rickshaw": 2}
    yaml_text = generate_dataset_yaml(
        dataset_dir="data/processed/datasets/v1",
        class_mapping=class_map,
        splits_present=["train", "val"],
    )
    assert "train: images/train" in yaml_text
    assert "val: images/val" in yaml_text
    assert "0: car" in yaml_text
    assert "1: bus" in yaml_text
    assert "2: auto_rickshaw" in yaml_text


def test_tp11_16_configuration_validation() -> None:
    """TP11-16: Configuration loader validates active_learning keys, types, and constraints."""
    # Valid default config
    cfg = load_config()
    assert "active_learning" in cfg
    assert cfg["active_learning"]["default_version"] == "v1"
    assert cfg["active_learning"]["split_strategy"] in ("video", "time_block")

    # Invalid split_strategy
    with pytest.raises(ConfigError, match="active_learning.split_strategy"):
        load_config(overrides={"active_learning": {"split_strategy": "invalid_strategy"}})

    # Invalid time_block_duration_s
    with pytest.raises(ConfigError, match="active_learning.time_block_duration_s"):
        load_config(overrides={"active_learning": {"time_block_duration_s": -10}})

    # Invalid split_ratios value
    with pytest.raises(ConfigError, match="active_learning.split_ratios"):
        load_config(overrides={"active_learning": {"split_ratios": {"train": 1.5}}})

    # Invalid duplicate_policy
    with pytest.raises(ConfigError, match="active_learning.duplicate_policy"):
        load_config(overrides={"active_learning": {"duplicate_policy": "unknown"}})

    # Invalid class_mapping
    with pytest.raises(ConfigError, match="active_learning.class_mapping"):
        load_config(overrides={"active_learning": {"class_mapping": "not_a_mapping"}})

    with pytest.raises(ConfigError, match="active_learning.class_mapping"):
        load_config(overrides={"active_learning": {"class_mapping": {"car": -1}}})
