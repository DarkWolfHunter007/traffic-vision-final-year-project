"""Small command-line entry point for Phase 01 bootstrap and ingestion."""

from __future__ import annotations

import argparse
import json
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
    return parser



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
        report = compare_counts(args.run_id, ground_truth_set_id=args.ground_truth_set, config=config, repository_root=REPOSITORY_ROOT)
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
