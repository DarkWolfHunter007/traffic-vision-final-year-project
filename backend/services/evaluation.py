"""Phase 12 model evaluation service: detection evaluation, counting validation, tracking evaluation, and production selection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from hashlib import sha256
import json
import logging
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

import cv2
import numpy as np

from backend.config import canonical_json, config_hash, load_config
from backend.database.connection import database_connection
from backend.database.repository import (
    fetch_all_model_versions,
    fetch_model_version,
    fetch_production_model,
    fetch_run_by_id,
    insert_model_version,
    set_production_model_version,
    update_model_metrics,
)
from backend.detection import Detector, UltralyticsDetector
from backend.evaluation import (
    EvaluationBox,
    EvaluationError,
    EvaluationLeakageError,
    audit_evaluation_leakage,
    calculate_confusion_matrix,
    calculate_detection_metrics,
    compare_model_metrics,
)
from backend.media import sha256_file
from backend.services.counting import compare_counts
from backend.services.dataset import get_dataset_manifest
from backend.tracking import evaluate_id_switches

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def register_model(
    model_version: str,
    model_path: Path | str,
    dataset_version: str | None = None,
    config: dict[str, Any] | None = None,
    repository_root: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Register a candidate model version in the canonical model_versions table.

    Computes cryptographic SHA-256 hash of model weights file and enforces unique versioning.
    """
    if not model_version or not str(model_version).strip():
        raise EvaluationError("model_version must be a non-empty string")

    if config is None:
        config = load_config()

    p = Path(model_path)
    if not p.is_absolute() and repository_root:
        p = repository_root / p

    if not p.is_file():
        raise EvaluationError(f"Model weights file does not exist: {p}")

    model_hash = sha256_file(p)
    created_at = _utc_now_iso()

    record = {
        "model_version": str(model_version).strip(),
        "model_path": str(p.resolve()),
        "sha256": model_hash,
        "dataset_version": dataset_version,
        "created_at": created_at,
        "selected_for_production": 0,
        "metrics_json": json.dumps({"evaluations": []}, sort_keys=True),
    }

    def _execute(conn: sqlite3.Connection) -> dict[str, Any]:
        existing = fetch_model_version(conn, str(model_version).strip())
        if existing is not None:
            raise EvaluationError(f"Model version '{model_version}' is already registered")
        insert_model_version(conn, record)
        return {
            "model_version": record["model_version"],
            "model_path": record["model_path"],
            "sha256": record["sha256"],
            "dataset_version": record["dataset_version"],
            "created_at": record["created_at"],
            "selected_for_production": 0,
        }

    if connection is not None:
        return _execute(connection)

    database_path = Path(config["paths"]["database_path"])
    if not database_path.is_absolute() and repository_root:
        database_path = repository_root / database_path

    with database_connection(database_path) as conn:
        return _execute(conn)



def evaluate_detection(
    model_version: str,
    dataset_path: Path | str | Mapping[str, Any],
    split: str = "val",
    detector: Detector | None = None,
    precomputed_predictions: Sequence[Sequence[EvaluationBox]] | None = None,
    config: dict[str, Any] | None = None,
    repository_root: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Evaluate candidate model detection metrics on a held-out dataset split.

    Enforces data leakage audit: strictly blocks evaluation on samples in the training split.
    Records model_version, dataset_manifest_hash, and config_hash on every evaluation.
    """
    if config is None:
        config = load_config()

    eval_cfg = config.get("evaluation", {})
    iou_thresh = float(eval_cfg.get("iou_threshold", 0.5))
    map_ious = [float(x) for x in eval_cfg.get("map_iou_thresholds", [0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95])]
    conf_thresh = float(eval_cfg.get("confidence_threshold", 0.25))

    # Load dataset manifest
    if isinstance(dataset_path, Mapping):
        manifest_data = dict(dataset_path)
        manifest_hash = sha256(canonical_json(manifest_data).encode("utf-8")).hexdigest()
        dataset_dir = repository_root or Path.cwd()
    else:
        p = Path(dataset_path)
        if not p.is_absolute() and repository_root:
            p = repository_root / p
        manifest_data = get_dataset_manifest(p)
        manifest_file = p if p.is_file() else p / "manifest.json"
        manifest_hash = sha256_file(manifest_file) if manifest_file.is_file() else sha256(canonical_json(manifest_data).encode("utf-8")).hexdigest()
        dataset_dir = p.parent if p.is_file() else p

    # Filter samples for the requested split
    all_samples = manifest_data.get("samples", [])
    target_samples = [s for s in all_samples if s.get("split") == split]

    if not target_samples:
        raise EvaluationError(f"No samples found for split '{split}' in dataset manifest")

    # Leakage check: ensure none of the evaluation samples are present in 'train' split
    eval_sample_ids = [s.get("sample_id") for s in target_samples if s.get("sample_id")]
    audit_evaluation_leakage(eval_sample_ids, manifest_data)

    # Resolve class mapping
    class_mapping = manifest_data.get("class_mapping", {})
    id_to_class = {int(v): k for k, v in class_mapping.items()}
    class_names = sorted(list(class_mapping.keys())) if class_mapping else ["car", "bus", "truck", "motorcycle", "auto_rickshaw"]

    # Build ground-truth boxes per sample
    ground_truths_by_sample: list[list[EvaluationBox]] = []
    for s in target_samples:
        gts: list[EvaluationBox] = []
        for ann in s.get("annotations", []):
            cid = int(ann.get("class_id", 0))
            cname = id_to_class.get(cid, str(cid))
            xc = float(ann.get("x_center", 0.0))
            yc = float(ann.get("y_center", 0.0))
            w = float(ann.get("width", 0.0))
            h = float(ann.get("height", 0.0))
            x1 = max(0.0, xc - w / 2.0)
            y1 = max(0.0, yc - h / 2.0)
            x2 = min(1.0, xc + w / 2.0)
            y2 = min(1.0, yc + h / 2.0)
            gts.append(EvaluationBox(class_name=cname, x1=x1, y1=y1, x2=x2, y2=y2, confidence=1.0))
        ground_truths_by_sample.append(gts)

    # Determine predictions per sample
    predictions_by_sample: list[list[EvaluationBox]] = []
    if precomputed_predictions is not None:
        if len(precomputed_predictions) != len(target_samples):
            raise EvaluationError(
                f"precomputed_predictions length ({len(precomputed_predictions)}) does not match sample count ({len(target_samples)})"
            )
        predictions_by_sample = [list(preds) for preds in precomputed_predictions]
    else:
        # If no detector passed, try loading UltralyticsDetector from registered model
        if detector is None:
            def _find_model(conn: sqlite3.Connection) -> str:
                m_row = fetch_model_version(conn, model_version)
                if m_row is None:
                    raise EvaluationError(f"Model version '{model_version}' not found")
                return str(m_row["model_path"])

            if connection is not None:
                weights_path = _find_model(connection)
            else:
                db_path = Path(config["paths"]["database_path"])
                if not db_path.is_absolute() and repository_root:
                    db_path = repository_root / db_path
                with database_connection(db_path) as conn:
                    weights_path = _find_model(conn)

            detector = UltralyticsDetector(Path(weights_path), device=config.get("resources", {}).get("policy", "cpu"))

        # Predict for each sample image
        for s in target_samples:
            img_rel = s.get("image_rel_path")
            if not img_rel:
                predictions_by_sample.append([])
                continue
            img_path = dataset_dir / img_rel
            if not img_path.is_file():
                predictions_by_sample.append([])
                continue
            img = cv2.imread(str(img_path))
            if img is None:
                predictions_by_sample.append([])
                continue
            h_img, w_img = img.shape[:2]
            raw_dets = detector.predict(img, confidence=conf_thresh, iou=iou_thresh, image_size=config.get("detection", {}).get("image_size", 640))
            preds: list[EvaluationBox] = []
            for rd in raw_dets:
                cname = rd.raw_class_name
                if config.get("detection", {}).get("class_mapping"):
                    cname = config["detection"]["class_mapping"].get(cname, cname)
                # Normalize coordinates to [0, 1]
                x1_n = rd.x1 / w_img
                y1_n = rd.y1 / h_img
                x2_n = rd.x2 / w_img
                y2_n = rd.y2 / h_img
                preds.append(EvaluationBox(class_name=cname, x1=x1_n, y1=y1_n, x2=x2_n, y2=y2_n, confidence=rd.confidence))
            predictions_by_sample.append(preds)

    # Compute detection metrics
    det_metrics = calculate_detection_metrics(
        predictions_by_sample=predictions_by_sample,
        ground_truths_by_sample=ground_truths_by_sample,
        class_names=class_names,
        iou_threshold=iou_thresh,
        map_iou_thresholds=map_ious,
    )

    evaluation_id = str(uuid4())
    eval_report = {
        "evaluation_id": evaluation_id,
        "evaluation_type": "detection",
        "model_version": model_version,
        "dataset_manifest_hash": manifest_hash,
        "config_hash": config_hash(config),
        "split_evaluated": split,
        "iou_threshold": iou_thresh,
        "total_samples": det_metrics["total_samples"],
        "total_ground_truth_boxes": det_metrics["total_ground_truth_boxes"],
        "total_predicted_boxes": det_metrics["total_predicted_boxes"],
        "macro_precision": det_metrics["macro_precision"],
        "macro_recall": det_metrics["macro_recall"],
        "map50": det_metrics["map50"],
        "map50_95": det_metrics["map50_95"],
        "class_metrics": det_metrics["class_metrics"],
        "confusion_matrix": det_metrics["confusion_matrix"],
        "evaluated_at": _utc_now_iso(),
    }

    # Persist report in model_versions.metrics_json
    def _save_metrics(conn: sqlite3.Connection) -> None:
        m_row = fetch_model_version(conn, model_version)
        if m_row is None:
            raise EvaluationError(f"Model version '{model_version}' not found")
        metrics_dict: dict[str, Any] = {}
        if m_row["metrics_json"]:
            try:
                metrics_dict = json.loads(m_row["metrics_json"])
            except Exception:
                metrics_dict = {}
        eval_list = metrics_dict.get("evaluations", [])
        eval_list.append(eval_report)
        metrics_dict["evaluations"] = eval_list
        metrics_dict["latest_detection"] = eval_report
        update_model_metrics(conn, model_version, canonical_json(metrics_dict))

    if connection is not None:
        _save_metrics(connection)
    else:
        db_path = Path(config["paths"]["database_path"])
        if not db_path.is_absolute() and repository_root:
            db_path = repository_root / db_path
        with database_connection(db_path) as conn:
            _save_metrics(conn)

    # Optionally write report artifact to output_dir
    out_dir_str = eval_cfg.get("output_dir", "data/processed/evaluations")
    out_dir = Path(out_dir_str)
    if not out_dir.is_absolute() and repository_root:
        out_dir = repository_root / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    report_file = out_dir / f"detection_{model_version}_{evaluation_id}.json"
    report_file.write_text(canonical_json(eval_report), encoding="utf-8")

    return eval_report


def evaluate_counting(
    model_version: str,
    run_id: str,
    ground_truth_set_id: str | None = None,
    config: dict[str, Any] | None = None,
    repository_root: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Evaluate vehicle counting performance of a run against Phase 06 ground truth.

    Compares against configured counting tolerance.
    Invariant: NEVER declares counter acceptance; research acceptance remains external.
    """
    if config is None:
        config = load_config()

    error_tol = float(config.get("counting", {}).get("error_tolerance_pct", 10.0))

    def _execute(conn: sqlite3.Connection) -> dict[str, Any]:
        m_row = fetch_model_version(conn, model_version)
        if m_row is None:
            raise EvaluationError(f"Model version '{model_version}' not found")

        run = fetch_run_by_id(conn, run_id)
        if run is None:
            raise EvaluationError(f"Processing run '{run_id}' not found")
        if run["status"] != "completed":
            raise EvaluationError(f"Processing run '{run_id}' is not completed (status={run['status']})")
        if run["model_version"] != model_version:
            raise EvaluationError(
                f"Processing run '{run_id}' used model_version '{run['model_version']}', not '{model_version}'"
            )

        # Run Phase 06 counting comparison
        cmp_report = compare_counts(
            run_id=run_id,
            ground_truth_set_id=ground_truth_set_id,
            config=config,
            repository_root=repository_root,
            connection=conn,
        )

        tot_pct_err = cmp_report.get("total_percent_error")
        tolerance_met = bool(tot_pct_err is not None and tot_pct_err <= error_tol)

        evaluation_id = str(uuid4())
        counting_report = {
            "evaluation_id": evaluation_id,
            "evaluation_type": "counting",
            "model_version": model_version,
            "run_id": run_id,
            "ground_truth_set_id": cmp_report.get("ground_truth_set_id"),
            "ground_truth_set_name": cmp_report.get("ground_truth_set_name"),
            "config_hash": config_hash(config),
            "error_tolerance_pct": error_tol,
            "total_counted": cmp_report["total_counted"],
            "total_observed": cmp_report["total_observed"],
            "total_absolute_error": cmp_report["total_absolute_error"],
            "total_percent_error": tot_pct_err,
            "tolerance_met": tolerance_met,
            "acceptance_status": "pending_independent_review",
            "acceptance_declaration": None,
            "research_acceptance": "external",
            "comparisons": cmp_report.get("comparisons", []),
            "evaluated_at": _utc_now_iso(),
        }

        # Update metrics_json in model_versions
        metrics_dict: dict[str, Any] = {}
        if m_row["metrics_json"]:
            try:
                metrics_dict = json.loads(m_row["metrics_json"])
            except Exception:
                metrics_dict = {}
        eval_list = metrics_dict.get("evaluations", [])
        eval_list.append(counting_report)
        metrics_dict["evaluations"] = eval_list
        metrics_dict["latest_counting"] = counting_report
        update_model_metrics(conn, model_version, canonical_json(metrics_dict))

        return counting_report

    if connection is not None:
        return _execute(connection)

    db_path = Path(config["paths"]["database_path"])
    if not db_path.is_absolute() and repository_root:
        db_path = repository_root / db_path
    with database_connection(db_path) as conn:
        return _execute(conn)


def evaluate_tracking(
    model_version: str,
    run_id: str,
    ground_truth_assignments: Sequence[tuple[int, int, int]] | None = None,
    config: dict[str, Any] | None = None,
    repository_root: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Evaluate tracking quality (CLEAR MOT ID switches) on a documented clip.

    Invariant: If ground-truth identities are missing, reports ID switches as None (N/A); never fabricates.
    """
    if config is None:
        config = load_config()

    def _execute(conn: sqlite3.Connection) -> dict[str, Any]:
        m_row = fetch_model_version(conn, model_version)
        if m_row is None:
            raise EvaluationError(f"Model version '{model_version}' not found")

        id_switches: int | None = None
        if ground_truth_assignments is not None:
            id_switches = evaluate_id_switches(ground_truth_assignments)

        evaluation_id = str(uuid4())
        tracking_report = {
            "evaluation_id": evaluation_id,
            "evaluation_type": "tracking",
            "model_version": model_version,
            "run_id": run_id,
            "config_hash": config_hash(config),
            "id_switches": id_switches,
            "track_continuity": None,  # Explicitly N/A when unmeasured
            "evaluated_at": _utc_now_iso(),
        }

        # Update metrics_json in model_versions
        metrics_dict: dict[str, Any] = {}
        if m_row["metrics_json"]:
            try:
                metrics_dict = json.loads(m_row["metrics_json"])
            except Exception:
                metrics_dict = {}
        eval_list = metrics_dict.get("evaluations", [])
        eval_list.append(tracking_report)
        metrics_dict["evaluations"] = eval_list
        metrics_dict["latest_tracking"] = tracking_report
        update_model_metrics(conn, model_version, canonical_json(metrics_dict))

        return tracking_report

    if connection is not None:
        return _execute(connection)

    db_path = Path(config["paths"]["database_path"])
    if not db_path.is_absolute() and repository_root:
        db_path = repository_root / db_path
    with database_connection(db_path) as conn:
        return _execute(conn)


def select_production_model(
    model_version: str,
    config: dict[str, Any] | None = None,
    repository_root: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Explicitly select and activate a production model.

    Prevents silent replacement: enforces database uniqueness invariant via atomic swap.
    """
    if config is None:
        config = load_config()

    def _execute(conn: sqlite3.Connection) -> dict[str, Any]:
        m_row = fetch_model_version(conn, model_version)
        if m_row is None:
            raise EvaluationError(f"Model version '{model_version}' does not exist")

        set_production_model_version(conn, model_version)
        return {
            "model_version": model_version,
            "selected_for_production": 1,
            "updated_at": _utc_now_iso(),
        }

    if connection is not None:
        return _execute(connection)

    db_path = Path(config["paths"]["database_path"])
    if not db_path.is_absolute() and repository_root:
        db_path = repository_root / db_path

    with database_connection(db_path) as conn:
        return _execute(conn)


def get_model_details(
    model_version: str,
    config: dict[str, Any] | None = None,
    repository_root: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Retrieve complete metadata and evaluation metrics for a model version."""
    if config is None:
        config = load_config()

    def _execute(conn: sqlite3.Connection) -> dict[str, Any]:
        row = fetch_model_version(conn, model_version)
        if row is None:
            raise EvaluationError(f"Model version '{model_version}' not found")
        metrics = {}
        if row["metrics_json"]:
            try:
                metrics = json.loads(row["metrics_json"])
            except Exception:
                metrics = {}
        return {
            "model_version": row["model_version"],
            "model_path": row["model_path"],
            "sha256": row["sha256"],
            "dataset_version": row["dataset_version"],
            "created_at": row["created_at"],
            "selected_for_production": int(row["selected_for_production"]),
            "metrics": metrics,
        }

    if connection is not None:
        return _execute(connection)

    db_path = Path(config["paths"]["database_path"])
    if not db_path.is_absolute() and repository_root:
        db_path = repository_root / db_path

    with database_connection(db_path) as conn:
        return _execute(conn)


def list_models(
    config: dict[str, Any] | None = None,
    repository_root: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """List all registered model versions."""
    if config is None:
        config = load_config()

    def _execute(conn: sqlite3.Connection) -> list[dict[str, Any]]:
        rows = fetch_all_model_versions(conn)
        results: list[dict[str, Any]] = []
        for row in rows:
            metrics = {}
            if row["metrics_json"]:
                try:
                    metrics = json.loads(row["metrics_json"])
                except Exception:
                    metrics = {}
            results.append({
                "model_version": row["model_version"],
                "model_path": row["model_path"],
                "sha256": row["sha256"],
                "dataset_version": row["dataset_version"],
                "created_at": row["created_at"],
                "selected_for_production": int(row["selected_for_production"]),
                "metrics": metrics,
            })
        return results

    if connection is not None:
        return _execute(connection)

    db_path = Path(config["paths"]["database_path"])
    if not db_path.is_absolute() and repository_root:
        db_path = repository_root / db_path

    with database_connection(db_path) as conn:
        return _execute(conn)


def compare_models(
    model_version_a: str,
    model_version_b: str,
    config: dict[str, Any] | None = None,
    repository_root: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Compare evaluation metrics between two registered models without overwriting either."""
    if config is None:
        config = load_config()

    def _execute(conn: sqlite3.Connection) -> dict[str, Any]:
        row_a = fetch_model_version(conn, model_version_a)
        if row_a is None:
            raise EvaluationError(f"Model version '{model_version_a}' not found")
        row_b = fetch_model_version(conn, model_version_b)
        if row_b is None:
            raise EvaluationError(f"Model version '{model_version_b}' not found")

        metrics_a = json.loads(row_a["metrics_json"]) if row_a["metrics_json"] else {}
        metrics_b = json.loads(row_b["metrics_json"]) if row_b["metrics_json"] else {}

        latest_det_a = metrics_a.get("latest_detection", {})
        latest_det_b = metrics_b.get("latest_detection", {})

        det_comp = compare_model_metrics(
            latest_det_a,
            latest_det_b,
            model_a_version=model_version_a,
            model_b_version=model_version_b,
        )

        return {
            "model_version_a": model_version_a,
            "model_version_b": model_version_b,
            "detection_comparison": det_comp,
            "compared_at": _utc_now_iso(),
        }

    if connection is not None:
        return _execute(connection)

    db_path = Path(config["paths"]["database_path"])
    if not db_path.is_absolute() and repository_root:
        db_path = repository_root / db_path

    with database_connection(db_path) as conn:
        return _execute(conn)

