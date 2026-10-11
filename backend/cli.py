"""Small command-line entry point for Phase 01 bootstrap and ingestion."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.config import load_config
from backend.database.connection import bootstrap_database
from backend.services.ingestion import ingest_video
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
