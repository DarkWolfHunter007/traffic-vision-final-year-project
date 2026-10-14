"""Phase 12 pure evaluation logic tests: TP12-02..07, TP12-12, TP12-16.

All test fixtures are synthetic software test fixtures; no real research data or CCTV measurements are fabricated.
"""

from __future__ import annotations

import pytest

from backend.config import ConfigError, load_config
from backend.evaluation import (
    EvaluationBox,
    EvaluationLeakageError,
    audit_evaluation_leakage,
    calculate_average_precision_for_class,
    calculate_box_iou,
    calculate_confusion_matrix,
    calculate_detection_metrics,
    calculate_precision_recall,
    compare_model_metrics,
    match_detections_for_image,
)


def test_tp12_box_iou_calculation() -> None:
    # Identical boxes -> 1.0
    assert calculate_box_iou((0.0, 0.0, 10.0, 10.0), (0.0, 0.0, 10.0, 10.0)) == 1.0

    # Non-overlapping boxes -> 0.0
    assert calculate_box_iou((0.0, 0.0, 5.0, 5.0), (10.0, 10.0, 15.0, 15.0)) == 0.0

    # 50% overlap box calculation
    # Box 1: [0, 0, 10, 10] area = 100
    # Box 2: [5, 0, 15, 10] area = 100
    # Intersection: [5, 0, 10, 10] area = 50
    # Union: 100 + 100 - 50 = 150 -> IoU = 50 / 150 = 1/3
    iou = calculate_box_iou((0.0, 0.0, 10.0, 10.0), (5.0, 0.0, 15.0, 10.0))
    assert pytest.approx(iou, rel=1e-3) == (50.0 / 150.0)


def test_tp12_02_leakage_audit_rejects_training_samples() -> None:
    synthetic_manifest = {
        "dataset_version": "v1-fixture",
        "samples": [
            {"sample_id": "s_train_1", "video_id": "vid1", "frame_number": 100, "split": "train"},
            {"sample_id": "s_train_2", "video_id": "vid1", "frame_number": 200, "split": "train"},
            {"sample_id": "s_val_1", "video_id": "vid2", "frame_number": 100, "split": "val"},
        ],
    }

    # Held-out samples that do not overlap should pass
    audit_evaluation_leakage(["s_val_1"], synthetic_manifest)
    audit_evaluation_leakage([("vid2", 100)], synthetic_manifest)

    # Samples present in the training split MUST be rejected
    with pytest.raises(EvaluationLeakageError, match="Data leakage detected: sample 's_train_1'"):
        audit_evaluation_leakage(["s_train_1"], synthetic_manifest)

    with pytest.raises(EvaluationLeakageError, match="Data leakage detected: frame 'vid1:200'"):
        audit_evaluation_leakage([("vid1", 200)], synthetic_manifest)


def test_tp12_03_detection_metrics_precision_recall_ap50() -> None:
    # 2 synthetic images with car detections
    gt_sample_1 = [
        EvaluationBox("car", 0.1, 0.1, 0.3, 0.3),
        EvaluationBox("car", 0.5, 0.5, 0.8, 0.8),
    ]
    gt_sample_2 = [
        EvaluationBox("car", 0.2, 0.2, 0.4, 0.4),
    ]

    # Perfect prediction for gt_sample_1, one TP and one FP for gt_sample_2
    pred_sample_1 = [
        EvaluationBox("car", 0.1, 0.1, 0.3, 0.3, confidence=0.9),
        EvaluationBox("car", 0.5, 0.5, 0.8, 0.8, confidence=0.85),
    ]
    pred_sample_2 = [
        EvaluationBox("car", 0.2, 0.2, 0.4, 0.4, confidence=0.8),  # TP
        EvaluationBox("car", 0.7, 0.7, 0.9, 0.9, confidence=0.6),  # FP
    ]

    metrics = calculate_detection_metrics(
        predictions_by_sample=[pred_sample_1, pred_sample_2],
        ground_truths_by_sample=[gt_sample_1, gt_sample_2],
        class_names=["car"],
        iou_threshold=0.5,
    )

    car_stats = metrics["class_metrics"]["car"]
    assert car_stats["ground_truth_count"] == 3
    assert car_stats["true_positives"] == 3
    assert car_stats["false_positives"] == 1
    assert car_stats["false_negatives"] == 0
    # Precision: 3 / (3 + 1) = 0.75
    assert car_stats["precision"] == 0.75
    # Recall: 3 / 3 = 1.0
    assert car_stats["recall"] == 1.0
    # AP50 is high
    assert car_stats["ap50"] is not None and car_stats["ap50"] > 0.9
    assert metrics["map50"] == car_stats["ap50"]


def test_tp12_04_map50_95_multi_threshold_evaluation() -> None:
    # Box with slight offset (IoU ~ 0.70)
    # Box 1: [0.1, 0.1, 0.5, 0.5] (area 0.16)
    # Box 2: [0.15, 0.15, 0.5, 0.5] (intersection [0.15, 0.15, 0.5, 0.5] area 0.35*0.35=0.1225)
    # IoU ~ 0.1225 / (0.16 + 0.1225 - 0.1225? no: area2 is 0.35*0.35=0.1225, union is 0.16) -> 0.1225/0.16 = 0.7656
    gts = [[EvaluationBox("bus", 0.1, 0.1, 0.5, 0.5)]]
    preds = [[EvaluationBox("bus", 0.15, 0.15, 0.5, 0.5, confidence=0.95)]]

    metrics = calculate_detection_metrics(
        predictions_by_sample=preds,
        ground_truths_by_sample=gts,
        class_names=["bus"],
        iou_threshold=0.5,
        map_iou_thresholds=[0.5, 0.6, 0.7, 0.8, 0.9],
    )

    bus_stats = metrics["class_metrics"]["bus"]
    # At IoU 0.5, 0.6, 0.7 -> TP (AP=1.0)
    # At IoU 0.8, 0.9 -> FP (AP=0.0)
    # Average across thresholds should be between 0.0 and 1.0
    assert bus_stats["ap50"] == 1.0
    assert bus_stats["ap50_95"] is not None
    assert 0.0 < bus_stats["ap50_95"] < 1.0
    assert metrics["map50_95"] == bus_stats["ap50_95"]


def test_tp12_05_confusion_matrix_computation() -> None:
    # 1 car ground truth matched to car prediction (TP)
    # 1 truck ground truth not detected (FN -> background)
    # 1 motorcycle prediction with no ground truth (FP -> background)
    gts = [
        [
            EvaluationBox("car", 0.1, 0.1, 0.3, 0.3),
            EvaluationBox("truck", 0.6, 0.6, 0.9, 0.9),
        ]
    ]
    preds = [
        [
            EvaluationBox("car", 0.1, 0.1, 0.3, 0.3, confidence=0.88),
            EvaluationBox("motorcycle", 0.4, 0.4, 0.5, 0.5, confidence=0.72),
        ]
    ]

    conf_matrix = calculate_confusion_matrix(
        predictions_by_sample=preds,
        ground_truths_by_sample=gts,
        class_names=["car", "truck", "motorcycle"],
        iou_threshold=0.5,
    )

    mat = conf_matrix["matrix"]
    # Car -> Car match (TP)
    assert mat["car"]["car"] == 1
    # Truck was missed -> Predicted is background (FN)
    assert mat["truck"]["background"] == 1
    # Motorcycle was predicted without GT -> True class was background (FP)
    assert mat["background"]["motorcycle"] == 1


def test_tp12_06_missing_data_reports_none_not_fabricated() -> None:
    # Class 'auto_rickshaw' has zero ground truth instances and zero predictions
    gts = [[EvaluationBox("car", 0.1, 0.1, 0.3, 0.3)]]
    preds = [[EvaluationBox("car", 0.1, 0.1, 0.3, 0.3, confidence=0.9)]]

    metrics = calculate_detection_metrics(
        predictions_by_sample=preds,
        ground_truths_by_sample=gts,
        class_names=["car", "auto_rickshaw"],
        iou_threshold=0.5,
    )

    auto_stats = metrics["class_metrics"]["auto_rickshaw"]
    assert auto_stats["ground_truth_count"] == 0
    # Must report None (N/A) rather than a fabricated 0.0
    assert auto_stats["precision"] is None
    assert auto_stats["recall"] is None
    assert auto_stats["ap50"] is None
    assert auto_stats["ap50_95"] is None


def test_tp12_12_side_by_side_model_comparison() -> None:
    metrics_a = {
        "map50": 0.72,
        "map50_95": 0.48,
        "macro_precision": 0.80,
        "macro_recall": 0.70,
    }
    metrics_b = {
        "map50": 0.78,
        "map50_95": 0.53,
        "macro_precision": 0.82,
        "macro_recall": 0.75,
    }

    comp = compare_model_metrics(metrics_a, metrics_b, model_a_version="yolo_v1", model_b_version="yolo_v2")
    assert comp["model_a_version"] == "yolo_v1"
    assert comp["model_b_version"] == "yolo_v2"
    diff = comp["metrics_diff"]
    assert diff["map50"]["delta"] == 0.06
    assert diff["map50_95"]["delta"] == 0.05
    assert diff["macro_precision"]["delta"] == 0.02
    assert diff["macro_recall"]["delta"] == 0.05


def test_tp12_16_configuration_validation() -> None:
    # Valid default config loads
    cfg = load_config()
    assert "evaluation" in cfg
    assert cfg["evaluation"]["iou_threshold"] == 0.5
    assert cfg["evaluation"]["held_out_split"] == "val"
    assert cfg["evaluation"]["counting_tolerance_pct"] == 10.0

    # Invalid iou_threshold
    with pytest.raises(ConfigError, match="evaluation.iou_threshold"):
        load_config(overrides={"evaluation": {"iou_threshold": -0.1}})

    with pytest.raises(ConfigError, match="evaluation.iou_threshold"):
        load_config(overrides={"evaluation": {"iou_threshold": 1.5}})

    # Invalid held_out_split
    with pytest.raises(ConfigError, match="evaluation.held_out_split"):
        load_config(overrides={"evaluation": {"held_out_split": "train"}})

    # Invalid counting_tolerance_pct
    with pytest.raises(ConfigError, match="evaluation.counting_tolerance_pct"):
        load_config(overrides={"evaluation": {"counting_tolerance_pct": -5.0}})

    # Invalid output_dir
    with pytest.raises(ConfigError, match="evaluation.output_dir"):
        load_config(overrides={"evaluation": {"output_dir": ""}})
