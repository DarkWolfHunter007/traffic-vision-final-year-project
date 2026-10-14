"""Small command-line entry point for Phase 01 bootstrap and ingestion."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.config import load_config
from backend.database.connection import bootstrap_database, migrate_database
from backend.detection import UltralyticsDetector
from backend.services.calibration import (
    get_calibration,
    run_calibration,
)
from backend.services.counting import (
    compare_counts,
    load_ground_truth,
    run_counting,
)
from backend.services.detection import run_detection
from backend.services.geometry_config import (
    load_geometry_config,
    render_geometry_preview,
)
from backend.services.ingestion import ingest_video
from backend.services.tracking import run_tracking
from backend.services.visualization import (
    render_preview_visualization,
    render_video_visualization,
)
from backend.services.speed import (
    get_speed_observations,
    run_speed_estimation,
)
from backend.services.queue import (
    get_queue_events,
    get_stop_events,
    run_queue_detection,
)
from backend.services.review import (
    create_manual_review,
    find_review_candidates,
    generate_snippet_for_review,
    get_manual_reviews,
    update_manual_review,
)
from backend.services.dataset import (
    audit_dataset_leakage_from_path,
    build_active_learning_dataset,
    get_dataset_manifest,
)
from backend.services.evaluation import (
    compare_models,
    evaluate_counting,
    evaluate_detection,
    get_model_details,
    register_model,
    select_production_model,
)
from backend.services.export import (
    export_run,
    get_export_manifest,
)
from backend.services.dashboard import (
    get_dashboard_run_summary,
)
from backend.structured_logging import configure_logging


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="traffic-vision")
    commands = parser.add_subparsers(dest="command", required=True)
    bootstrap = commands.add_parser("bootstrap-db", help="Apply the canonical SQLite schema")
    bootstrap.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs" / "default.yaml")
    ingest = commands.add_parser("ingest", help="Ingest one supported recorded video")
    ingest.add_argument("video", type=Path)
    ingest.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs" / "default.yaml")
    ingest.add_argument("--wall-clock-start")
    ingest.add_argument("--parent-run-id")
    detect = commands.add_parser("detect", help="Run configured detection for an ingested parent run")
    detect.add_argument("parent_run_id")
    detect.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs" / "default.yaml")
    track = commands.add_parser("track", help="Run configured ByteTrack tracking for a detection parent run")
    track.add_argument("parent_run_id")
    track.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs" / "default.yaml")
    visualize = commands.add_parser("visualize", help="Render trajectory visualization for a tracking parent run")
    visualize.add_argument("parent_run_id")
    visualize.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs" / "default.yaml")
    visualize.add_argument("--output", type=Path, default=None)
    visualize.add_argument("--preview-frame", type=int, default=None)
    visualize.add_argument("--start-frame", type=int, default=None)
    visualize.add_argument("--end-frame", type=int, default=None)
    load_geom = commands.add_parser("load-geometry", help="Load and validate geometry configuration for a video")
    load_geom.add_argument("video_id")
    load_geom.add_argument("config_path", type=Path)
    load_geom.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs" / "default.yaml")
    show_geom = commands.add_parser("show-geometry", help="Render configured lines and zones overlaid on a video frame")
    show_geom.add_argument("video_id")
    show_geom.add_argument("--output", type=Path, required=True)
    show_geom.add_argument("--frame", type=int, default=0)
    show_geom.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs" / "default.yaml")
    count_cmd = commands.add_parser("count", help="Run configured vehicle counting for a tracking parent run")
    count_cmd.add_argument("parent_run_id")
    count_cmd.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs" / "default.yaml")
    load_gt = commands.add_parser("load-ground-truth", help="Load ground-truth counting dataset from a file")
    load_gt.add_argument("file", type=Path)
    load_gt.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs" / "default.yaml")
    cmp_counts = commands.add_parser("compare-counts", help="Compare counting results against ground-truth dataset")
    cmp_counts.add_argument("run_id")
    cmp_counts.add_argument("--ground-truth-set", default=None)
    cmp_counts.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs" / "default.yaml")
    migrate_cmd = commands.add_parser("migrate-db", help="Explicitly upgrade the canonical SQLite database schema")
    migrate_cmd.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs" / "default.yaml")
    calib_cmd = commands.add_parser("calibrate", help="Run planar homography camera calibration from reference points")
    calib_cmd.add_argument("target", help="Parent processing run ID or video ID")
    calib_cmd.add_argument("points_file", type=Path, help="Path to YAML or JSON reference points file")
    calib_cmd.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs" / "default.yaml")
    show_calib = commands.add_parser("show-calibration", help="Inspect an existing calibration run and its diagnostics")
    show_calib.add_argument("calibration_id", help="Calibration ID")
    show_calib.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs" / "default.yaml")
    estimate_spd = commands.add_parser("estimate-speed", help="Run calibrated speed estimation for a tracking parent run")
    estimate_spd.add_argument("parent_run_id", help="Parent tracking processing run ID")
    estimate_spd.add_argument("--calibration-id", default=None, help="Optional accepted calibration ID")
    estimate_spd.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs" / "default.yaml")
    show_spd = commands.add_parser("show-speed", help="Inspect speed observations for a speed run")
    show_spd.add_argument("run_id", help="Speed estimation processing run ID")
    show_spd.add_argument("--track-id", type=int, default=None, help="Optional track ID filter")
    show_spd.add_argument("--limit", type=int, default=None, help="Optional maximum rows to return")
    show_spd.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs" / "default.yaml")
    detect_q = commands.add_parser("detect-queue", help="Run stopped vehicle and calibrated queue detection")
    detect_q.add_argument("parent_run_id", help="Parent processing run ID")
    detect_q.add_argument("--calibration-id", default=None, help="Optional accepted calibration ID")
    detect_q.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs" / "default.yaml")
    show_q = commands.add_parser("show-queue", help="Inspect queue events for a queue run")
    show_q.add_argument("run_id", help="Queue detection processing run ID")
    show_q.add_argument("--zone-id", default=None, help="Optional zone ID filter")
    show_q.add_argument("--approach", default=None, help="Optional approach filter")
    show_q.add_argument("--limit", type=int, default=None, help="Optional maximum rows to return")
    show_q.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs" / "default.yaml")
    show_stops = commands.add_parser("show-stops", help="Inspect stop events for a queue run")
    show_stops.add_argument("run_id", help="Queue detection processing run ID")
    show_stops.add_argument("--track-id", type=int, default=None, help="Optional track ID filter")
    show_stops.add_argument("--limit", type=int, default=None, help="Optional maximum rows to return")
    show_stops.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs" / "default.yaml")

    find_cands = commands.add_parser("find-review-candidates", help="Find uncertain detections and tracks flagged for review")
    find_cands.add_argument("parent_run_id", help="Parent processing run ID")
    find_cands.add_argument("--confidence-threshold", type=float, default=None, help="Optional confidence threshold override")
    find_cands.add_argument("--limit", type=int, default=None, help="Optional maximum candidates to return")
    find_cands.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs" / "default.yaml")

    create_rev = commands.add_parser("create-review", help="Create an auditable manual review / correction record")
    create_rev.add_argument("parent_run_id", help="Parent processing run ID")
    create_rev.add_argument("--frame", type=int, required=True, help="Frame number")
    create_rev.add_argument("--timestamp", type=float, required=True, help="Authoritative timestamp in seconds")
    create_rev.add_argument("--reason", required=True, help="Review reason (e.g. low_confidence, class_ambiguity)")
    create_rev.add_argument("--detection-id", default=None, help="Optional detection ID")
    create_rev.add_argument("--track-id", type=int, default=None, help="Optional track ID")
    create_rev.add_argument("--reviewer", default="analyst", help="Reviewer username/identifier")
    create_rev.add_argument("--original-class", default=None, help="Original predicted class")
    create_rev.add_argument("--corrected-class", default=None, help="Corrected class label")
    create_rev.add_argument("--original-bbox", default=None, help="Original bbox as JSON or x1,y1,x2,y2")
    create_rev.add_argument("--corrected-bbox", default=None, help="Corrected bbox as JSON or x1,y1,x2,y2")
    create_rev.add_argument("--status", default="pending", help="Review status (pending, approved, rejected)")
    create_rev.add_argument("--generate-snippet", action="store_true", help="Generate before/after event snippet clip")
    create_rev.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs" / "default.yaml")

    show_revs = commands.add_parser("show-reviews", help="Query and inspect manual reviews")
    show_revs.add_argument("--run-id", default=None, help="Optional run ID filter")
    show_revs.add_argument("--video-id", default=None, help="Optional video ID filter")
    show_revs.add_argument("--status", default=None, help="Optional status filter")
    show_revs.add_argument("--reviewer", default=None, help="Optional reviewer filter")
    show_revs.add_argument("--track-id", type=int, default=None, help="Optional track ID filter")
    show_revs.add_argument("--detection-id", default=None, help="Optional detection ID filter")
    show_revs.add_argument("--limit", type=int, default=None, help="Optional maximum rows to return")
    show_revs.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs" / "default.yaml")

    update_rev = commands.add_parser("update-review", help="Update review status, reviewer, or correction")
    update_rev.add_argument("review_id", help="Manual review ID")
    update_rev.add_argument("--status", default=None, help="New review status")
    update_rev.add_argument("--corrected-class", default=None, help="Corrected vehicle class")
    update_rev.add_argument("--corrected-bbox", default=None, help="Corrected bbox as JSON or x1,y1,x2,y2")
    update_rev.add_argument("--reviewer", default=None, help="Reviewer identifier")
    update_rev.add_argument("--reason", default=None, help="Review reason or update note")
    update_rev.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs" / "default.yaml")

    gen_snip = commands.add_parser("generate-review-snippet", help="Generate before/after video snippet for a review item")
    gen_snip.add_argument("review_id", help="Manual review ID")
    gen_snip.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs" / "default.yaml")

    export_ds = commands.add_parser("export-dataset", help="Export YOLO-format active-learning dataset from approved reviews")
    export_ds.add_argument("--output-dir", type=Path, default=None, help="Output root directory")
    export_ds.add_argument("--version", default=None, help="Dataset version identifier")
    export_ds.add_argument("--run-id", default=None, help="Optional parent processing run ID filter")
    export_ds.add_argument("--video-id", default=None, help="Optional video ID filter")
    export_ds.add_argument("--split-strategy", choices=["video", "time_block"], default=None, help="Split grouping strategy")
    export_ds.add_argument("--train-ratio", type=float, default=None, help="Train split ratio (0.0-1.0)")
    export_ds.add_argument("--val-ratio", type=float, default=None, help="Val split ratio (0.0-1.0)")
    export_ds.add_argument("--seed", type=int, default=None, help="Random seed for deterministic split assignment")
    export_ds.add_argument("--no-images", action="store_true", help="Skip extracting image files, export labels and manifest only")
    export_ds.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs" / "default.yaml")

    show_manifest = commands.add_parser("show-dataset-manifest", help="Inspect an exported dataset manifest")
    show_manifest.add_argument("path", type=Path, help="Dataset directory or manifest.json file path")
    show_manifest.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs" / "default.yaml")

    audit_leakage = commands.add_parser("audit-dataset-leakage", help="Audit an exported dataset for split leakage")
    audit_leakage.add_argument("path", type=Path, help="Dataset directory or manifest.json file path")
    audit_leakage.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs" / "default.yaml")

    reg_model = commands.add_parser("register-model", help="Register a candidate model version")
    reg_model.add_argument("version", help="Model version identifier")
    reg_model.add_argument("path", type=Path, help="Model weights file path")
    reg_model.add_argument("--dataset-version", default=None, help="Dataset version used for model")
    reg_model.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs" / "default.yaml")

    eval_det = commands.add_parser("evaluate-detection", help="Evaluate model detection performance on held-out split")
    eval_det.add_argument("model_version", help="Model version identifier")
    eval_det.add_argument("dataset_path", type=Path, help="Dataset directory or manifest.json path")
    eval_det.add_argument("--split", default="val", help="Dataset split to evaluate (val or test)")
    eval_det.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs" / "default.yaml")

    eval_cnt = commands.add_parser("evaluate-counting", help="Evaluate model counting against Phase 06 ground truth")
    eval_cnt.add_argument("model_version", help="Model version identifier")
    eval_cnt.add_argument("run_id", help="Counting processing run ID")
    eval_cnt.add_argument("--ground-truth-set", default=None, help="Ground truth set ID")
    eval_cnt.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs" / "default.yaml")

    cmp_mod = commands.add_parser("compare-models", help="Compare evaluation metrics between two models")
    cmp_mod.add_argument("model_a", help="First model version")
    cmp_mod.add_argument("model_b", help="Second model version")
    cmp_mod.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs" / "default.yaml")

    sel_mod = commands.add_parser("select-model", help="Select production active model")
    sel_mod.add_argument("model_version", help="Model version identifier to activate")
    sel_mod.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs" / "default.yaml")

    show_mod = commands.add_parser("show-model", help="Show model metadata and evaluations")
    show_mod.add_argument("model_version", help="Model version identifier")
    show_mod.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs" / "default.yaml")

    export_cmd = commands.add_parser("export", help="Export processing run data in CSV, JSON, and SQLite formats")
    export_cmd.add_argument("run_id", help="Processing run ID to export")
    export_cmd.add_argument("--output-dir", type=Path, default=None, help="Target export directory")
    export_cmd.add_argument("--format", default="all", choices=["all", "csv", "json", "sqlite"], help="Export format")
    export_cmd.add_argument("--no-raw", action="store_true", help="Exclude raw crossing events from export")
    export_cmd.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs" / "default.yaml")

    show_export_man = commands.add_parser("show-export-manifest", help="Inspect an exported run manifest")
    show_export_man.add_argument("path", type=Path, help="Manifest file or export directory path")
    show_export_man.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs" / "default.yaml")

    dash_summary = commands.add_parser("dashboard-summary", help="Retrieve aggregate dashboard summary for a run")
    dash_summary.add_argument("run_id", help="Processing run ID")
    dash_summary.add_argument("--config", type=Path, default=REPOSITORY_ROOT / "configs" / "default.yaml")
    return parser



def _parse_bbox_arg(val: str | None) -> dict[str, float] | None:
    if val is None:
        return None
    val = val.strip()
    if val.startswith("{"):
        return json.loads(val)
    if "," in val:
        parts = [float(p.strip()) for p in val.split(",")]
        if len(parts) != 4:
            raise ValueError(f"Bounding box string must have 4 comma-separated numbers (x1,y1,x2,y2), got {val}")
        return {"x1": parts[0], "y1": parts[1], "x2": parts[2], "y2": parts[3]}
    raise ValueError(f"Unrecognized bounding box format: {val}")




def main() -> None:
    args = build_parser().parse_args()
    config = load_config(args.config)
    configure_logging(config["logging"]["level"])
    database_path = Path(config["paths"]["database_path"])
    if not database_path.is_absolute():
        database_path = REPOSITORY_ROOT / database_path
    if args.command == "bootstrap-db":
        print(json.dumps({"database_path": str(database_path), "schema_version": bootstrap_database(database_path)}))
        return
    if args.command == "detect":
        model = config["detection"]["model"]
        if not model["path"]:
            raise SystemExit("detection.model.path must be configured before detection can run")
        model_path = Path(model["path"])
        if not model_path.is_absolute():
            model_path = REPOSITORY_ROOT / model_path
        run_id = run_detection(
            args.parent_run_id,
            config,
            REPOSITORY_ROOT,
            UltralyticsDetector(model_path, model["device"]),
        )
        print(json.dumps({"run_id": run_id, "parent_run_id": args.parent_run_id}, sort_keys=True))
        return
    if args.command == "track":
        run_id = run_tracking(args.parent_run_id, config, REPOSITORY_ROOT)
        print(json.dumps({"run_id": run_id, "parent_run_id": args.parent_run_id}, sort_keys=True))
        return
    if args.command == "visualize":
        if args.preview_frame is not None and args.preview_frame < 0:
            raise SystemExit("preview-frame must be >= 0")
        if args.start_frame is not None and args.start_frame < 0:
            raise SystemExit("start-frame must be >= 0")
        if args.end_frame is not None and args.end_frame < 0:
            raise SystemExit("end-frame must be >= 0")
        if args.start_frame is not None and args.end_frame is not None and args.start_frame > args.end_frame:
            raise SystemExit(f"start-frame ({args.start_frame}) cannot be greater than end-frame ({args.end_frame})")

        if args.preview_frame is not None:
            output_path = render_preview_visualization(
                args.parent_run_id,
                args.preview_frame,
                config,
                REPOSITORY_ROOT,
                output_path=args.output,
            )
            print(
                json.dumps(
                    {
                        "parent_run_id": args.parent_run_id,
                        "preview_frame": args.preview_frame,
                        "output_path": str(output_path),
                    },
                    sort_keys=True,
                )
            )
            return
        run_id = render_video_visualization(
            args.parent_run_id,
            config,
            REPOSITORY_ROOT,
            output_path=args.output,
            start_frame=args.start_frame,
            end_frame=args.end_frame,
        )
        print(json.dumps({"run_id": run_id, "parent_run_id": args.parent_run_id}, sort_keys=True))
        return
    if args.command == "load-geometry":
        result = load_geometry_config(
            args.video_id,
            args.config_path,
            config=config,
            repository_root=REPOSITORY_ROOT,
        )
        print(json.dumps(result, sort_keys=True))
        return
    if args.command == "show-geometry":
        if args.frame < 0:
            raise SystemExit("frame must be >= 0")
        output_path = render_geometry_preview(
            args.video_id,
            args.output,
            frame_number=args.frame,
            config=config,
            repository_root=REPOSITORY_ROOT,
        )
        print(
            json.dumps(
                {
                    "video_id": args.video_id,
                    "output_path": str(output_path),
                    "frame": args.frame,
                },
                sort_keys=True,
            )
        )
        return
    if args.command == "migrate-db":
        print(json.dumps({"database_path": str(database_path), "schema_version": migrate_database(database_path)}))
        return
    if args.command == "count":
        run_id = run_counting(args.parent_run_id, config, REPOSITORY_ROOT)
        print(json.dumps({"run_id": run_id, "parent_run_id": args.parent_run_id}, sort_keys=True))
        return
    if args.command == "load-ground-truth":
        result = load_ground_truth(args.file, config=config, repository_root=REPOSITORY_ROOT)
        print(json.dumps(result, sort_keys=True))
        return
    if args.command == "compare-counts":
        try:
            report = compare_counts(args.run_id, ground_truth_set_id=args.ground_truth_set, config=config, repository_root=REPOSITORY_ROOT)
        except ValueError as err:
            print(json.dumps({"error": str(err), "run_id": args.run_id, "status": "unavailable"}, sort_keys=True), file=sys.stderr)
            raise SystemExit(1)
        print(json.dumps(report, sort_keys=True))
        return
    if args.command == "calibrate":
        result = run_calibration(
            args.target,
            args.points_file,
            config=config,
            repository_root=REPOSITORY_ROOT,
        )
        print(json.dumps(result, sort_keys=True))
        return
    if args.command == "show-calibration":
        calib = get_calibration(
            args.calibration_id,
            config=config,
            repository_root=REPOSITORY_ROOT,
        )
        if calib is None:
            raise SystemExit(f"Calibration '{args.calibration_id}' not found")
        print(json.dumps(calib, sort_keys=True))
        return
    if args.command == "estimate-speed":
        result = run_speed_estimation(
            args.parent_run_id,
            calibration_id=args.calibration_id,
            config=config,
            repository_root=REPOSITORY_ROOT,
        )
        print(json.dumps(result, sort_keys=True))
        return
    if args.command == "show-speed":
        result = get_speed_observations(
            args.run_id,
            track_id=args.track_id,
            limit=args.limit,
            config=config,
            repository_root=REPOSITORY_ROOT,
        )
        print(json.dumps(result, sort_keys=True))
        return
    if args.command == "detect-queue":
        result = run_queue_detection(
            args.parent_run_id,
            calibration_id=args.calibration_id,
            config=config,
            repository_root=REPOSITORY_ROOT,
        )
        print(json.dumps(result, sort_keys=True))
        return
    if args.command == "show-queue":
        result = get_queue_events(
            args.run_id,
            zone_id=args.zone_id,
            approach=args.approach,
            limit=args.limit,
            config=config,
            repository_root=REPOSITORY_ROOT,
        )
        print(json.dumps(result, sort_keys=True))
        return
    if args.command == "show-stops":
        result = get_stop_events(
            args.run_id,
            track_id=args.track_id,
            limit=args.limit,
            config=config,
            repository_root=REPOSITORY_ROOT,
        )
        print(json.dumps(result, sort_keys=True))
        return
    if args.command == "find-review-candidates":
        result = find_review_candidates(
            args.parent_run_id,
            confidence_threshold=args.confidence_threshold,
            limit=args.limit,
            config=config,
            repository_root=REPOSITORY_ROOT,
        )
        print(json.dumps(result, sort_keys=True))
        return
    if args.command == "create-review":
        orig_box = _parse_bbox_arg(args.original_bbox)
        corr_box = _parse_bbox_arg(args.corrected_bbox)
        result = create_manual_review(
            args.parent_run_id,
            frame_number=args.frame,
            timestamp_s=args.timestamp,
            reason=args.reason,
            detection_id=args.detection_id,
            track_id=args.track_id,
            reviewer=args.reviewer,
            original_class=args.original_class,
            corrected_class=args.corrected_class,
            original_bbox=orig_box,
            corrected_bbox=corr_box,
            status=args.status,
            generate_snippet=args.generate_snippet,
            config=config,
            repository_root=REPOSITORY_ROOT,
        )
        print(json.dumps(result, sort_keys=True))
        return
    if args.command == "show-reviews":
        result = get_manual_reviews(
            run_id=args.run_id,
            video_id=args.video_id,
            review_status=args.status,
            reviewer=args.reviewer,
            track_id=args.track_id,
            detection_id=args.detection_id,
            limit=args.limit,
            config=config,
            repository_root=REPOSITORY_ROOT,
        )
        print(json.dumps(result, sort_keys=True))
        return
    if args.command == "update-review":
        corr_box = _parse_bbox_arg(args.corrected_bbox)
        result = update_manual_review(
            args.review_id,
            status=args.status,
            corrected_class=args.corrected_class,
            corrected_bbox=corr_box,
            reviewer=args.reviewer,
            reason=args.reason,
            config=config,
            repository_root=REPOSITORY_ROOT,
        )
        print(json.dumps(result, sort_keys=True))
        return
    if args.command == "generate-review-snippet":
        snip_path = generate_snippet_for_review(
            args.review_id,
            config=config,
            repository_root=REPOSITORY_ROOT,
        )
        print(json.dumps({"review_id": args.review_id, "snippet_path": str(snip_path)}, sort_keys=True))
        return
    if args.command == "export-dataset":
        ratios = None
        if args.train_ratio is not None or args.val_ratio is not None:
            tr = args.train_ratio if args.train_ratio is not None else 0.8
            vr = args.val_ratio if args.val_ratio is not None else 0.2
            ratios = {"train": tr, "val": vr, "test": 0.0}
        result = build_active_learning_dataset(
            output_dir=args.output_dir,
            dataset_version=args.version,
            run_id=args.run_id,
            video_id=args.video_id,
            split_ratios=ratios,
            split_strategy=args.split_strategy,
            seed=args.seed,
            export_images=not args.no_images,
            config=config,
            repository_root=REPOSITORY_ROOT,
        )
        print(json.dumps(result, sort_keys=True))
        return
    if args.command == "show-dataset-manifest":
        manifest_data = get_dataset_manifest(args.path)
        print(json.dumps(manifest_data, sort_keys=True))
        return
    if args.command == "audit-dataset-leakage":
        audit_res = audit_dataset_leakage_from_path(args.path)
        print(json.dumps(audit_res, sort_keys=True))
        return
    if args.command == "register-model":
        result = register_model(
            model_version=args.version,
            model_path=args.path,
            dataset_version=args.dataset_version,
            config=config,
            repository_root=REPOSITORY_ROOT,
        )
        print(json.dumps(result, sort_keys=True))
        return
    if args.command == "evaluate-detection":
        result = evaluate_detection(
            model_version=args.model_version,
            dataset_path=args.dataset_path,
            split=args.split,
            config=config,
            repository_root=REPOSITORY_ROOT,
        )
        print(json.dumps(result, sort_keys=True))
        return
    if args.command == "evaluate-counting":
        result = evaluate_counting(
            model_version=args.model_version,
            run_id=args.run_id,
            ground_truth_set_id=args.ground_truth_set,
            config=config,
            repository_root=REPOSITORY_ROOT,
        )
        print(json.dumps(result, sort_keys=True))
        return
    if args.command == "compare-models":
        result = compare_models(
            model_version_a=args.model_a,
            model_version_b=args.model_b,
            config=config,
            repository_root=REPOSITORY_ROOT,
        )
        print(json.dumps(result, sort_keys=True))
        return
    if args.command == "select-model":
        result = select_production_model(
            model_version=args.model_version,
            config=config,
            repository_root=REPOSITORY_ROOT,
        )
        print(json.dumps(result, sort_keys=True))
        return
    if args.command == "show-model":
        result = get_model_details(
            model_version=args.model_version,
            config=config,
            repository_root=REPOSITORY_ROOT,
        )
        print(json.dumps(result, sort_keys=True))
        return
    if args.command == "export":
        result = export_run(
            run_id=args.run_id,
            output_dir=args.output_dir,
            export_format=args.format,
            include_raw=not args.no_raw,
            config=config,
            repository_root=REPOSITORY_ROOT,
        )
        print(json.dumps(result, sort_keys=True))
        return
    if args.command == "show-export-manifest":
        manifest_path = args.path if args.path.is_file() else args.path / "manifest.json"
        manifest_data = get_export_manifest(manifest_path)
        print(json.dumps(manifest_data, sort_keys=True))
        return
    if args.command == "dashboard-summary":
        summary = get_dashboard_run_summary(
            run_id=args.run_id,
            config=config,
            repository_root=REPOSITORY_ROOT,
        )
        print(json.dumps(summary, sort_keys=True))
        return

    result = ingest_video(
        args.video,
        config,
        repository_root=REPOSITORY_ROOT,
        parent_run_id=args.parent_run_id,
        wall_clock_start=args.wall_clock_start,
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
