"""Export orchestration service for Phase 13."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping

from backend.config import load_config
from backend.database.connection import database_connection
from backend.database.repository import (
    fetch_run_export_data,
)
from backend.export import (
    build_export_manifest,
    compute_content_hash,
    compute_observed_period_summary,
    file_sha256,
    format_csv_data,
    generate_sqlite_export_database,
)


def _resolve_db_path(config: Mapping[str, Any] | None, repository_root: Path | None) -> Path:
    cfg = config or load_config()
    db_path = Path(cfg.get("paths", {}).get("database_path", "data/processed/traffic_vision.sqlite3"))
    if not db_path.is_absolute() and repository_root:
        db_path = repository_root / db_path
    return db_path


def export_run(
    run_id: str,
    output_dir: str | Path | None = None,
    export_format: str = "all",
    include_raw: bool = True,
    config: Mapping[str, Any] | None = None,
    repository_root: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Orchestrate multi-format export for a processing run with deterministic content hashing and manifest."""
    cfg = config or load_config()

    def _execute(conn: sqlite3.Connection) -> dict[str, Any]:
        data = fetch_run_export_data(conn, run_id, include_raw=include_raw)
        if data is None:
            raise ValueError(f"Processing run '{run_id}' not found in database")

        run_info = data["run"]
        video_info = data["video"] or {}
        volume_bins = data["traffic_volume_bins"]
        crossing_events = data["crossing_events"]
        speed_observations = data["speed_observations"]
        stop_events = data["stop_events"]
        queue_events = data["queue_events"]
        manual_reviews = data["manual_reviews"]
        tracking_quality = data["tracking_quality"]
        speed_stats = data["speed_stats"]
        queue_stats = data["queue_stats"]
        review_stats = data["review_stats"]
        calibration = data["calibration"]

        # Calculate observed-period summary from volume bins
        observed_period_summary = compute_observed_period_summary(volume_bins)

        base_out = Path(output_dir or cfg.get("export", {}).get("output_dir", "data/processed/exports"))
        if not base_out.is_absolute() and repository_root:
            base_out = repository_root / base_out
        target_dir = base_out / run_id
        target_dir.mkdir(parents=True, exist_ok=True)

        selected_fmt = export_format.lower()
        if selected_fmt not in {"all", "csv", "json", "sqlite"}:
            raise ValueError(f"Unsupported export format '{export_format}'; allowed: 'all', 'csv', 'json', 'sqlite'")

        exported_files: dict[str, str] = {}

        # 1. CSV Exports
        if selected_fmt in {"all", "csv"}:
            # Volume bins CSV
            bin_fields = [
                "bin_id", "run_id", "video_id", "line_id", "bin_start_s",
                "bin_duration_s", "observed_duration_s", "vehicle_class",
                "approach", "movement", "count", "extrapolated_vehicles_per_hour",
            ]
            bins_csv_text = format_csv_data(volume_bins, bin_fields)
            bins_file = target_dir / "traffic_volume_bins.csv"
            bins_file.write_text(bins_csv_text, encoding="utf-8")
            exported_files["traffic_volume_bins.csv"] = file_sha256(bins_file)

            # Observed period summary CSV
            obs_fields = [
                "run_id", "video_id", "approach", "movement", "vehicle_class",
                "count", "observed_duration_s", "extrapolated_vehicles_per_hour",
            ]
            obs_csv_text = format_csv_data(observed_period_summary, obs_fields)
            obs_file = target_dir / "observed_period_summary.csv"
            obs_file.write_text(obs_csv_text, encoding="utf-8")
            exported_files["observed_period_summary.csv"] = file_sha256(obs_file)

            # Speed observations CSV
            speed_fields = [
                "speed_observation_id", "run_id", "video_id", "track_id",
                "timestamp_s", "speed_mps", "speed_kmh", "calibration_id",
                "status", "smoothing_window", "ground_point_method",
            ]
            speed_csv_text = format_csv_data(speed_observations, speed_fields)
            speed_file = target_dir / "speed_observations.csv"
            speed_file.write_text(speed_csv_text, encoding="utf-8")
            exported_files["speed_observations.csv"] = file_sha256(speed_file)

            # Stop events CSV
            stop_fields = [
                "stop_event_id", "run_id", "video_id", "track_id",
                "start_timestamp_s", "end_timestamp_s", "duration_s",
                "threshold_kmh", "status",
            ]
            stop_csv_text = format_csv_data(stop_events, stop_fields)
            stop_file = target_dir / "stop_events.csv"
            stop_file.write_text(stop_csv_text, encoding="utf-8")
            exported_files["stop_events.csv"] = file_sha256(stop_file)

            # Queue events CSV
            queue_fields = [
                "queue_event_id", "run_id", "video_id", "zone_id", "approach",
                "timestamp_s", "queue_length_m", "queued_vehicle_count", "status",
            ]
            queue_csv_text = format_csv_data(queue_events, queue_fields)
            queue_file = target_dir / "queue_events.csv"
            queue_file.write_text(queue_csv_text, encoding="utf-8")
            exported_files["queue_events.csv"] = file_sha256(queue_file)

            # Raw crossings CSV if included
            if include_raw:
                cross_fields = [
                    "crossing_event_id", "run_id", "video_id", "line_id",
                    "track_id", "frame_number", "timestamp_s", "vehicle_class",
                    "direction", "approach", "movement", "line_config_version",
                    "deduplicated",
                ]
                cross_csv_text = format_csv_data(crossing_events, cross_fields)
                cross_file = target_dir / "crossing_events.csv"
                cross_file.write_text(cross_csv_text, encoding="utf-8")
                exported_files["crossing_events.csv"] = file_sha256(cross_file)

            # Manual reviews CSV
            rev_fields = [
                "review_id", "run_id", "video_id", "track_id", "detection_id",
                "frame_number", "timestamp_s", "original_class", "corrected_class",
                "original_bbox_json", "corrected_bbox_json", "reason",
                "review_status", "reviewer", "reviewed_at", "snippet_path",
            ]
            rev_csv_text = format_csv_data(manual_reviews, rev_fields)
            rev_file = target_dir / "manual_reviews.csv"
            rev_file.write_text(rev_csv_text, encoding="utf-8")
            exported_files["manual_reviews.csv"] = file_sha256(rev_file)

        # 2. JSON Export
        json_payload = {
            "run_metadata": run_info,
            "video_metadata": video_info,
            "traffic_volume_bins": volume_bins,
            "observed_period_summary": observed_period_summary,
            "tracking_quality": tracking_quality,
            "speed_summary": speed_stats,
            "queue_summary": queue_stats,
            "review_status": review_stats,
            "calibration": calibration,
        }
        if include_raw:
            json_payload["crossing_events_count"] = len(crossing_events)
            json_payload["speed_observations_count"] = len(speed_observations)
            json_payload["stop_events_count"] = len(stop_events)
            json_payload["queue_events_count"] = len(queue_events)

        if selected_fmt in {"all", "json"}:
            json_file = target_dir / "run_summary.json"
            json_text = json.dumps(json_payload, indent=2, sort_keys=True, ensure_ascii=False)
            json_file.write_text(json_text, encoding="utf-8")
            exported_files["run_summary.json"] = file_sha256(json_file)

        # 3. SQLite Export
        if selected_fmt in {"all", "sqlite"}:
            sqlite_file = target_dir / "export.sqlite"
            sqlite_tables = {
                "videos": [video_info] if video_info else [],
                "processing_runs": [run_info],
                "traffic_volume_bins": volume_bins,
                "observed_period_summary": observed_period_summary,
                "crossing_events": crossing_events if include_raw else [],
                "speed_observations": speed_observations,
                "stop_events": stop_events,
                "queue_events": queue_events,
                "manual_reviews": manual_reviews,
            }
            generate_sqlite_export_database(sqlite_file, sqlite_tables)
            exported_files["export.sqlite"] = file_sha256(sqlite_file)

        # Content hash deterministically computed from payload content (excluding export_timestamp)
        content_hash = compute_content_hash(json_payload)

        # Build and write manifest
        manifest = build_export_manifest(
            run_metadata=run_info,
            exported_files=exported_files,
            content_hash=content_hash,
        )
        manifest_file = target_dir / "manifest.json"
        manifest_file.write_text(
            json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )

        return {
            "run_id": run_id,
            "export_dir": str(target_dir),
            "manifest_path": str(manifest_file),
            "content_hash": content_hash,
            "exported_files": list(exported_files.keys()),
            "manifest": manifest,
        }

    if connection is not None:
        return _execute(connection)

    db_path = _resolve_db_path(cfg, repository_root)
    with database_connection(db_path) as conn:
        return _execute(conn)


def get_export_manifest(manifest_path: Path | str) -> dict[str, Any]:
    """Read and validate an export manifest JSON from disk."""
    p = Path(manifest_path)
    if not p.is_file():
        raise FileNotFoundError(f"Export manifest not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))
