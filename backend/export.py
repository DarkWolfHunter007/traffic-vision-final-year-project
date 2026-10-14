"""Pure export logic module for Phase 13: deterministic CSV, JSON, and SQLite exports."""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from hashlib import sha256
import io
import json
from pathlib import Path
import sqlite3
from typing import Any, Mapping, Sequence


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def compute_observed_period_summary(
    bins: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Compute aggregate observed-period volume and hourly rate from Phase 06 bins."""
    if not bins:
        return []

    # Determine the contiguous or total observed period duration across all bins
    period_start = min(float(b.get("bin_start_s", 0.0)) for b in bins)
    period_end = max(
        float(b.get("bin_start_s", 0.0))
        + float(b.get("observed_duration_s") or b.get("bin_duration_s", 900.0))
        for b in bins
    )
    observed_period_duration_s = max(0.0, period_end - period_start)

    groups: dict[tuple[str | None, str | None, str | None], int] = {}
    run_id = bins[0].get("run_id", "")
    video_id = bins[0].get("video_id", "")

    for b in bins:
        approach = b.get("approach")
        movement = b.get("movement")
        v_class = b.get("vehicle_class")
        count = int(b.get("count", 0))
        key = (approach, movement, v_class)
        groups[key] = groups.get(key, 0) + count

    summary_rows: list[dict[str, Any]] = []
    for (approach, movement, v_class), total_count in sorted(
        groups.items(), key=lambda item: (str(item[0][0]), str(item[0][1]), str(item[0][2]))
    ):
        extrapolated_vph = (
            round((total_count * 3600.0) / observed_period_duration_s, 2)
            if observed_period_duration_s > 0
            else None
        )
        summary_rows.append(
            {
                "run_id": run_id,
                "video_id": video_id,
                "approach": approach,
                "movement": movement,
                "vehicle_class": v_class,
                "count": total_count,
                "observed_duration_s": observed_period_duration_s,
                "extrapolated_vehicles_per_hour": extrapolated_vph,
            }
        )

    return summary_rows


def compute_content_hash(data_payload: Mapping[str, Any]) -> str:
    """Compute deterministic SHA-256 hash over data content, strictly excluding export_timestamp."""
    # Deep copy / filter payload to exclude any export_timestamp or manifest-level timestamp
    filtered = {}
    for k, v in sorted(data_payload.items()):
        if k in {"export_timestamp", "exported_at", "created_at_manifest"}:
            continue
        filtered[k] = v

    canonical = json.dumps(filtered, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(canonical.encode("utf-8")).hexdigest()


def build_export_manifest(
    run_metadata: Mapping[str, Any],
    exported_files: Mapping[str, str],
    content_hash: str,
    export_timestamp: str | None = None,
) -> dict[str, Any]:
    """Assemble manifest retaining run, video, model, config, and schema provenance."""
    return {
        "manifest_version": "1.0",
        "run_id": run_metadata.get("run_id"),
        "source_video_sha256": run_metadata.get("source_video_sha256"),
        "model_version": run_metadata.get("model_version"),
        "config_hash": run_metadata.get("config_hash"),
        "schema_version": run_metadata.get("schema_version"),
        "code_version": run_metadata.get("code_version"),
        "export_timestamp": export_timestamp or _utc_now(),
        "content_hash": content_hash,
        "exported_files": dict(sorted(exported_files.items())),
    }


def format_csv_data(rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str]) -> str:
    """Format rows into deterministic CSV string with standard header and sorted keys."""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(fieldnames), lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        cleaned = {k: ("" if row.get(k) is None else row.get(k)) for k in fieldnames}
        writer.writerow(cleaned)
    return out.getvalue()


def file_sha256(file_path: Path) -> str:
    """Compute SHA-256 hash of a file on disk."""
    return sha256(file_path.read_bytes()).hexdigest()


SQLITE_EXPORT_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS videos (
    video_id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    fps_nominal REAL,
    width INTEGER,
    height INTEGER,
    duration_s REAL,
    frame_count INTEGER,
    variable_frame_rate INTEGER NOT NULL DEFAULT 0,
    wall_clock_start TEXT,
    ingested_at TEXT NOT NULL,
    metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS processing_runs (
    run_id TEXT PRIMARY KEY,
    parent_run_id TEXT,
    video_id TEXT NOT NULL REFERENCES videos(video_id),
    model_version TEXT,
    config_hash TEXT NOT NULL,
    config_json TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    code_version TEXT NOT NULL,
    source_video_sha256 TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS traffic_volume_bins (
    bin_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES processing_runs(run_id),
    video_id TEXT NOT NULL REFERENCES videos(video_id),
    line_id TEXT NOT NULL,
    bin_start_s REAL NOT NULL,
    bin_duration_s REAL NOT NULL DEFAULT 900,
    observed_duration_s REAL,
    vehicle_class TEXT,
    approach TEXT,
    movement TEXT,
    count INTEGER NOT NULL,
    extrapolated_vehicles_per_hour REAL
);

CREATE TABLE IF NOT EXISTS observed_period_summary (
    summary_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    video_id TEXT NOT NULL,
    approach TEXT,
    movement TEXT,
    vehicle_class TEXT,
    count INTEGER NOT NULL,
    observed_duration_s REAL,
    extrapolated_vehicles_per_hour REAL
);

CREATE TABLE IF NOT EXISTS crossing_events (
    crossing_event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    video_id TEXT NOT NULL,
    line_id TEXT NOT NULL,
    track_id INTEGER NOT NULL,
    frame_number INTEGER NOT NULL,
    timestamp_s REAL NOT NULL,
    vehicle_class TEXT,
    direction TEXT,
    approach TEXT,
    movement TEXT,
    line_config_version TEXT NOT NULL,
    deduplicated INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS speed_observations (
    speed_observation_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    video_id TEXT NOT NULL,
    track_id INTEGER NOT NULL,
    timestamp_s REAL NOT NULL,
    speed_mps REAL,
    speed_kmh REAL,
    calibration_id TEXT,
    status TEXT NOT NULL,
    smoothing_window REAL,
    ground_point_method TEXT NOT NULL DEFAULT 'bottom_center'
);

CREATE TABLE IF NOT EXISTS stop_events (
    stop_event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    video_id TEXT NOT NULL,
    track_id INTEGER NOT NULL,
    start_timestamp_s REAL NOT NULL,
    end_timestamp_s REAL,
    duration_s REAL,
    threshold_kmh REAL NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS queue_events (
    queue_event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    video_id TEXT NOT NULL,
    zone_id TEXT,
    approach TEXT,
    timestamp_s REAL NOT NULL,
    queue_length_m REAL,
    queued_vehicle_count INTEGER,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS manual_reviews (
    review_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    video_id TEXT NOT NULL,
    track_id INTEGER,
    detection_id TEXT,
    frame_number INTEGER NOT NULL,
    timestamp_s REAL NOT NULL,
    original_class TEXT,
    corrected_class TEXT,
    original_bbox_json TEXT,
    corrected_bbox_json TEXT,
    reason TEXT NOT NULL,
    review_status TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    snippet_path TEXT
);
"""


def generate_sqlite_export_database(
    target_path: Path,
    tables_data: Mapping[str, Sequence[Mapping[str, Any]]],
) -> None:
    """Generate a clean standalone SQLite database containing exported records in deterministic order."""
    if target_path.exists():
        target_path.unlink()
    target_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(target_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SQLITE_EXPORT_SCHEMA)

        # Insert tables in dependency order
        # 1. videos
        if "videos" in tables_data:
            for row in tables_data["videos"]:
                cols = list(row.keys())
                placeholders = ",".join(f":{c}" for c in cols)
                conn.execute(
                    f"INSERT OR IGNORE INTO videos ({','.join(cols)}) VALUES ({placeholders})",
                    dict(row),
                )

        # 2. processing_runs
        if "processing_runs" in tables_data:
            for row in tables_data["processing_runs"]:
                cols = list(row.keys())
                placeholders = ",".join(f":{c}" for c in cols)
                conn.execute(
                    f"INSERT OR IGNORE INTO processing_runs ({','.join(cols)}) VALUES ({placeholders})",
                    dict(row),
                )

        # 3. traffic_volume_bins
        if "traffic_volume_bins" in tables_data:
            for row in tables_data["traffic_volume_bins"]:
                cols = list(row.keys())
                placeholders = ",".join(f":{c}" for c in cols)
                conn.execute(
                    f"INSERT OR IGNORE INTO traffic_volume_bins ({','.join(cols)}) VALUES ({placeholders})",
                    dict(row),
                )

        # 4. observed_period_summary
        if "observed_period_summary" in tables_data:
            for row in tables_data["observed_period_summary"]:
                cols = [c for c in row.keys() if c != "summary_id"]
                placeholders = ",".join(f":{c}" for c in cols)
                conn.execute(
                    f"INSERT INTO observed_period_summary ({','.join(cols)}) VALUES ({placeholders})",
                    {c: row.get(c) for c in cols},
                )

        # 5. crossing_events
        if "crossing_events" in tables_data:
            for row in tables_data["crossing_events"]:
                cols = list(row.keys())
                placeholders = ",".join(f":{c}" for c in cols)
                conn.execute(
                    f"INSERT OR IGNORE INTO crossing_events ({','.join(cols)}) VALUES ({placeholders})",
                    dict(row),
                )

        # 6. speed_observations
        if "speed_observations" in tables_data:
            for row in tables_data["speed_observations"]:
                cols = list(row.keys())
                placeholders = ",".join(f":{c}" for c in cols)
                conn.execute(
                    f"INSERT OR IGNORE INTO speed_observations ({','.join(cols)}) VALUES ({placeholders})",
                    dict(row),
                )

        # 7. stop_events
        if "stop_events" in tables_data:
            for row in tables_data["stop_events"]:
                cols = list(row.keys())
                placeholders = ",".join(f":{c}" for c in cols)
                conn.execute(
                    f"INSERT OR IGNORE INTO stop_events ({','.join(cols)}) VALUES ({placeholders})",
                    dict(row),
                )

        # 8. queue_events
        if "queue_events" in tables_data:
            for row in tables_data["queue_events"]:
                cols = list(row.keys())
                placeholders = ",".join(f":{c}" for c in cols)
                conn.execute(
                    f"INSERT OR IGNORE INTO queue_events ({','.join(cols)}) VALUES ({placeholders})",
                    dict(row),
                )

        # 9. manual_reviews
        if "manual_reviews" in tables_data:
            for row in tables_data["manual_reviews"]:
                cols = list(row.keys())
                placeholders = ",".join(f":{c}" for c in cols)
                conn.execute(
                    f"INSERT OR IGNORE INTO manual_reviews ({','.join(cols)}) VALUES ({placeholders})",
                    dict(row),
                )

        conn.commit()
    finally:
        conn.close()
