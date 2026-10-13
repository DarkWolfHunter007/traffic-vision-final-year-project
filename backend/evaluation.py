"""Phase 12 pure evaluation logic: detection metrics, confusion matrix, leakage audit, and model comparison."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence


class EvaluationError(ValueError):
    """Base exception for model evaluation errors."""


class EvaluationLeakageError(EvaluationError):
    """Raised when evaluation data overlaps with training data."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def calculate_box_iou(
    box1: tuple[float, float, float, float] | Sequence[float],
    box2: tuple[float, float, float, float] | Sequence[float],
) -> float:
    """Compute Intersection-over-Union (IoU) between two bounding boxes [x1, y1, x2, y2]."""
    x1 = max(float(box1[0]), float(box2[0]))
    y1 = max(float(box1[1]), float(box2[1]))
    x2 = min(float(box1[2]), float(box2[2]))
    y2 = min(float(box1[3]), float(box2[3]))

    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area1 = max(0.0, float(box1[2]) - float(box1[0])) * max(0.0, float(box1[3]) - float(box1[1]))
    area2 = max(0.0, float(box2[2]) - float(box2[0])) * max(0.0, float(box2[3]) - float(box2[1]))
    union = area1 + area2 - intersection
    if union <= 0.0:
        return 0.0
    return intersection / union


@dataclass(frozen=True)
class EvaluationBox:
    """Bounding box for detection evaluation."""
    class_name: str
    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float = 1.0

    @property
    def coords(self) -> tuple[float, float, float, float]:
        return (self.x1, self.y1, self.x2, self.y2)


def audit_evaluation_leakage(
    evaluation_sample_identifiers: Sequence[str | tuple[str, int]],
    dataset_manifest: Mapping[str, Any],
) -> None:
    """Verify that NO evaluated sample or frame belongs to the training split of the dataset.

    Parameters:
        evaluation_sample_identifiers: Sequence of sample_ids or (video_id, frame_number) tuples.
        dataset_manifest: Parsed manifest.json dictionary from Phase 11.

    Raises:
        EvaluationLeakageError: If any sample is found in the 'train' split of the manifest.
    """
    train_sample_ids: set[str] = set()
    train_frame_tuples: set[tuple[str, int]] = set()

    samples = dataset_manifest.get("samples", [])
    for sample in samples:
        split = sample.get("split")
        if split == "train":
            s_id = str(sample.get("sample_id", ""))
            if s_id:
                train_sample_ids.add(s_id)
            v_id = str(sample.get("video_id", ""))
            fn = sample.get("frame_number")
            if v_id and fn is not None:
                train_frame_tuples.add((v_id, int(fn)))

    for ident in evaluation_sample_identifiers:
        if isinstance(ident, str):
            if ident in train_sample_ids:
                raise EvaluationLeakageError(
                    f"Data leakage detected: sample '{ident}' is present in the training split of dataset version '{dataset_manifest.get('dataset_version')}'"
                )
        elif isinstance(ident, (tuple, list)) and len(ident) >= 2:
            key = (str(ident[0]), int(ident[1]))
            if key in train_frame_tuples:
                raise EvaluationLeakageError(
                    f"Data leakage detected: frame '{key[0]}:{key[1]}' is present in the training split of dataset version '{dataset_manifest.get('dataset_version')}'"
                )


def calculate_precision_recall(
    tp: int, fp: int, fn: int
) -> tuple[float | None, float | None]:
    """Calculate precision and recall; returns None when denominator is zero."""
    precision = (tp / (tp + fp)) if (tp + fp) > 0 else None
    recall = (tp / (tp + fn)) if (tp + fn) > 0 else None
    return precision, recall


def calculate_average_precision_for_class(
    predictions_with_eval: Sequence[tuple[float, bool]],
    total_ground_truths: int,
) -> float | None:
    """Calculate 11-point interpolated Average Precision (AP) for a single class.

    Parameters:
        predictions_with_eval: List of (confidence, is_true_positive) for all predictions of this class across all images.
        total_ground_truths: Total number of ground-truth instances for this class.

    Returns:
        AP as a float in [0.0, 1.0], or None (N/A) if total_ground_truths == 0 (no data).
    """
    if total_ground_truths == 0:
        return None
    if not predictions_with_eval:
        return 0.0

    # Sort predictions by confidence descending
    sorted_preds = sorted(predictions_with_eval, key=lambda x: x[0], reverse=True)

    tp_cum = 0
    fp_cum = 0
    recalls: list[float] = []
    precisions: list[float] = []

    for _, is_tp in sorted_preds:
        if is_tp:
            tp_cum += 1
        else:
            fp_cum += 1
        rec = tp_cum / total_ground_truths
        prec = tp_cum / (tp_cum + fp_cum)
        recalls.append(rec)
        precisions.append(prec)

    # 11-point interpolated AP calculation across standard recall thresholds: 0.0, 0.1, ..., 1.0
    recall_thresholds = [i / 10.0 for i in range(11)]
    interpolated_precisions: list[float] = []

    for r_thresh in recall_thresholds:
        # Find maximum precision for recall >= r_thresh
        prec_candidates = [p for r, p in zip(recalls, precisions) if r >= r_thresh]
        if prec_candidates:
            interpolated_precisions.append(max(prec_candidates))
        else:
            interpolated_precisions.append(0.0)

    ap = sum(interpolated_precisions) / len(interpolated_precisions)
    return round(ap, 4)


def match_detections_for_image(
    predictions: Sequence[EvaluationBox],
    ground_truths: Sequence[EvaluationBox],
    iou_threshold: float = 0.5,
) -> tuple[list[tuple[EvaluationBox, EvaluationBox]], list[EvaluationBox], list[EvaluationBox]]:
    """Greedily match predicted boxes to ground truth boxes for an image.

    Matching is class-aware: only boxes of the exact same class can match.
    Returns:
        (matches, false_positives, false_negatives)
    """
    matches: list[tuple[EvaluationBox, EvaluationBox]] = []
    false_positives: list[EvaluationBox] = []

    # Group ground truths by class
    gt_by_class: dict[str, list[EvaluationBox]] = defaultdict(list)
    for gt in ground_truths:
        gt_by_class[gt.class_name].append(gt)

    matched_gt_ids: set[int] = set()

    # Sort predictions by confidence descending
    sorted_preds = sorted(predictions, key=lambda p: p.confidence, reverse=True)

    for pred in sorted_preds:
        candidates = gt_by_class.get(pred.class_name, [])
        best_iou = 0.0
        best_gt_idx = -1

        for idx, gt in enumerate(candidates):
            gt_id = id(gt)
            if gt_id in matched_gt_ids:
                continue
            iou = calculate_box_iou(pred.coords, gt.coords)
            if iou >= iou_threshold and iou > best_iou:
                best_iou = iou
                best_gt_idx = idx

        if best_gt_idx >= 0:
            matched_gt = candidates[best_gt_idx]
            matched_gt_ids.add(id(matched_gt))
            matches.append((pred, matched_gt))
        else:
            false_positives.append(pred)

    false_negatives: list[EvaluationBox] = [
        gt for gt in ground_truths if id(gt) not in matched_gt_ids
    ]

    return matches, false_positives, false_negatives


def calculate_confusion_matrix(
    predictions_by_sample: Sequence[Sequence[EvaluationBox]],
    ground_truths_by_sample: Sequence[Sequence[EvaluationBox]],
    class_names: Sequence[str],
    iou_threshold: float = 0.5,
) -> dict[str, Any]:
    """Compute class-to-class confusion matrix including background (unmatched).

    Rows represent Ground Truth class; Columns represent Predicted class.
    'background' row accounts for False Positives (predictions with no GT).
    'background' column accounts for False Negatives (GT with no matching prediction).
    """
    ordered_classes = sorted(list(class_names))
    matrix_labels = ordered_classes + ["background"]

    # Initialize confusion matrix grid: matrix[gt_class][pred_class]
    matrix: dict[str, dict[str, int]] = {
        row_cls: {col_cls: 0 for col_cls in matrix_labels}
        for row_cls in matrix_labels
    }

    for preds, gts in zip(predictions_by_sample, ground_truths_by_sample):
        matches, fps, fns = match_detections_for_image(preds, gts, iou_threshold=iou_threshold)

        # True positives
        for p, g in matches:
            p_cls = p.class_name if p.class_name in matrix else "background"
            g_cls = g.class_name if g.class_name in matrix else "background"
            matrix[g_cls][p_cls] += 1

        # False positives: prediction with no ground truth -> GT is background
        for p in fps:
            p_cls = p.class_name if p.class_name in matrix else "background"
            matrix["background"][p_cls] += 1

        # False negatives: ground truth with no prediction -> Predicted is background
        for g in fns:
            g_cls = g.class_name if g.class_name in matrix else "background"
            matrix[g_cls]["background"] += 1

    return {
        "classes": matrix_labels,
        "matrix": matrix,
    }


def calculate_detection_metrics(
    predictions_by_sample: Sequence[Sequence[EvaluationBox]],
    ground_truths_by_sample: Sequence[Sequence[EvaluationBox]],
    class_names: Sequence[str],
    iou_threshold: float = 0.5,
    map_iou_thresholds: Sequence[float] | None = None,
) -> dict[str, Any]:
    """Calculate comprehensive detection metrics: class-wise AP, macro mAP@50, mAP@50:95, and precision/recall.

    Invariant: If a class has 0 ground-truth instances, its AP is reported as None (N/A), never 0.0 or fabricated.
    """
    if map_iou_thresholds is None:
        map_iou_thresholds = [0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95]

    ordered_classes = sorted(list(class_names))

    # Tally ground truth instances per class
    gt_counts: dict[str, int] = {c: 0 for c in ordered_classes}
    for gts in ground_truths_by_sample:
        for g in gts:
            if g.class_name in gt_counts:
                gt_counts[g.class_name] += 1

    # Match at the primary iou_threshold (default 0.5) to compute AP@50 and per-class TP/FP/FN
    preds_eval_50: dict[str, list[tuple[float, bool]]] = {c: [] for c in ordered_classes}
    tp_by_class: dict[str, int] = {c: 0 for c in ordered_classes}
    fp_by_class: dict[str, int] = {c: 0 for c in ordered_classes}
    fn_by_class: dict[str, int] = {c: 0 for c in ordered_classes}

    total_pred_boxes = 0
    total_gt_boxes = sum(gt_counts.values())

    for preds, gts in zip(predictions_by_sample, ground_truths_by_sample):
        total_pred_boxes += len(preds)
        matches, fps, fns = match_detections_for_image(preds, gts, iou_threshold=iou_threshold)

        for p, _ in matches:
            if p.class_name in preds_eval_50:
                preds_eval_50[p.class_name].append((p.confidence, True))
                tp_by_class[p.class_name] += 1

        for p in fps:
            if p.class_name in preds_eval_50:
                preds_eval_50[p.class_name].append((p.confidence, False))
                fp_by_class[p.class_name] += 1

        for g in fns:
            if g.class_name in fn_by_class:
                fn_by_class[g.class_name] += 1

    # Compute AP@50 per class
    ap50_by_class: dict[str, float | None] = {}
    precision_by_class: dict[str, float | None] = {}
    recall_by_class: dict[str, float | None] = {}

    for c in ordered_classes:
        prec, rec = calculate_precision_recall(tp_by_class[c], fp_by_class[c], fn_by_class[c])
        precision_by_class[c] = round(prec, 4) if prec is not None else None
        recall_by_class[c] = round(rec, 4) if rec is not None else None
        ap50 = calculate_average_precision_for_class(preds_eval_50[c], gt_counts[c])
        ap50_by_class[c] = ap50

    # Compute AP across map_iou_thresholds for mAP@50:95
    ap_all_thresholds_by_class: dict[str, list[float | None]] = {c: [] for c in ordered_classes}
    for thresh in map_iou_thresholds:
        preds_eval_t: dict[str, list[tuple[float, bool]]] = {c: [] for c in ordered_classes}
        for preds, gts in zip(predictions_by_sample, ground_truths_by_sample):
            matches, fps, _ = match_detections_for_image(preds, gts, iou_threshold=thresh)
            for p, _ in matches:
                if p.class_name in preds_eval_t:
                    preds_eval_t[p.class_name].append((p.confidence, True))
            for p in fps:
                if p.class_name in preds_eval_t:
                    preds_eval_t[p.class_name].append((p.confidence, False))

        for c in ordered_classes:
            ap_t = calculate_average_precision_for_class(preds_eval_t[c], gt_counts[c])
            ap_all_thresholds_by_class[c].append(ap_t)

    ap50_95_by_class: dict[str, float | None] = {}
    for c in ordered_classes:
        valid_aps = [val for val in ap_all_thresholds_by_class[c] if val is not None]
        if valid_aps:
            ap50_95_by_class[c] = round(sum(valid_aps) / len(valid_aps), 4)
        else:
            ap50_95_by_class[c] = None

    # Macro averages over classes that have ground truth instances > 0
    evaluated_ap50s = [val for val in ap50_by_class.values() if val is not None]
    evaluated_ap50_95s = [val for val in ap50_95_by_class.values() if val is not None]
    evaluated_precisions = [val for val in precision_by_class.values() if val is not None]
    evaluated_recalls = [val for val in recall_by_class.values() if val is not None]

    macro_map50 = round(sum(evaluated_ap50s) / len(evaluated_ap50s), 4) if evaluated_ap50s else None
    macro_map50_95 = round(sum(evaluated_ap50_95s) / len(evaluated_ap50_95s), 4) if evaluated_ap50_95s else None
    macro_precision = round(sum(evaluated_precisions) / len(evaluated_precisions), 4) if evaluated_precisions else None
    macro_recall = round(sum(evaluated_recalls) / len(evaluated_recalls), 4) if evaluated_recalls else None

    # Confusion matrix
    conf_matrix = calculate_confusion_matrix(
        predictions_by_sample, ground_truths_by_sample, ordered_classes, iou_threshold=iou_threshold
    )

    class_metrics: dict[str, dict[str, Any]] = {}
    for c in ordered_classes:
        class_metrics[c] = {
            "ground_truth_count": gt_counts[c],
            "true_positives": tp_by_class[c],
            "false_positives": fp_by_class[c],
            "false_negatives": fn_by_class[c],
            "precision": precision_by_class[c],
            "recall": recall_by_class[c],
            "ap50": ap50_by_class[c],
            "ap50_95": ap50_95_by_class[c],
        }

    return {
        "total_samples": len(predictions_by_sample),
        "total_ground_truth_boxes": total_gt_boxes,
        "total_predicted_boxes": total_pred_boxes,
        "macro_precision": macro_precision,
        "macro_recall": macro_recall,
        "map50": macro_map50,
        "map50_95": macro_map50_95,
        "class_metrics": class_metrics,
        "confusion_matrix": conf_matrix,
    }


def compare_model_metrics(
    model_a_metrics: Mapping[str, Any],
    model_b_metrics: Mapping[str, Any],
    model_a_version: str = "model_a",
    model_b_version: str = "model_b",
) -> dict[str, Any]:
    """Compute side-by-side metric comparison between two evaluated models.

    Invariant: Does not mutate models, overwrite versions, or declare an automated winner.
    """
    keys_to_compare = ["map50", "map50_95", "macro_precision", "macro_recall"]
    diff: dict[str, Any] = {}

    for key in keys_to_compare:
        val_a = model_a_metrics.get(key)
        val_b = model_b_metrics.get(key)
        delta = None
        if isinstance(val_a, (int, float)) and isinstance(val_b, (int, float)):
            delta = round(float(val_b) - float(val_a), 4)
        diff[key] = {
            model_a_version: val_a,
            model_b_version: val_b,
            "delta": delta,
        }

    return {
        "model_a_version": model_a_version,
        "model_b_version": model_b_version,
        "metrics_diff": diff,
        "compared_at": _utc_now(),
    }
