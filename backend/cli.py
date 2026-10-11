"""Small command-line entry point for Phase 01 bootstrap and ingestion."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.config import load_config
from backend.database.connection import bootstrap_database
from backend.detection import UltralyticsDetector
from backend.services.detection import run_detection
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
