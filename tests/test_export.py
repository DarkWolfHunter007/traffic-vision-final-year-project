"""Unit tests for Phase 13 pure export logic (TP13-01..TP13-06, TP13-11)."""

from __future__ import annotations

import sqlite3
from typing import Any

from backend.export import (
    build_export_manifest,
    compute_content_hash,
    compute_observed_period_summary,
    format_csv_data,
    generate_sqlite_export_database,
)


def test_tp13_01_csv_export_deterministic_formatting() -> None:
    """TP13-01: CSV formatting is deterministic with exact headers and empty string for nulls."""
    rows = [
        {"bin_id": "bin_02", "count": 15, "extrapolated_vph": 60.0, "notes": None},
        {"bin_id": "bin_01", "count": 10, "extrapolated_vph": None, "notes": "first"},
    ]
    fieldnames = ["bin_id", "count", "extrapolated_vph", "notes"]
    csv_text_1 = format_csv_data(rows, fieldnames)
    csv_text_2 = format_csv_data(rows, fieldnames)

    assert csv_text_1 == csv_text_2
    lines = csv_text_1.strip().split("\n")
    assert lines[0] == "bin_id,count,extrapolated_vph,notes"
    assert lines[1] == "bin_02,15,60.0,"
    assert lines[2] == "bin_01,10,,first"


def test_tp13_02_observed_period_summary_calculation() -> None:
    """TP13-06: 15-minute and observed-period summaries correctly aggregate duration, counts, and vph."""
    # Labelled synthetic software fixture
    bins = [
        {
            "bin_id": "b1",
            "run_id": "run_test_01",
            "video_id": "vid_test",
            "bin_start_s": 0.0,
            "observed_duration_s": 900.0,
            "approach": "north",
            "movement": "through",
            "vehicle_class": "car",
            "count": 25,
        },
        {
            "bin_id": "b2",
            "run_id": "run_test_01",
            "video_id": "vid_test",
            "bin_start_s": 900.0,
            "observed_duration_s": 900.0,
            "approach": "north",
            "movement": "through",
            "vehicle_class": "car",
            "count": 35,
        },
        {
            "bin_id": "b3",
            "run_id": "run_test_01",
            "video_id": "vid_test",
            "bin_start_s": 0.0,
            "observed_duration_s": 900.0,
            "approach": "south",
            "movement": "left",
            "vehicle_class": "bus",
            "count": 5,
        },
    ]

    summary = compute_observed_period_summary(bins)
    assert len(summary) == 2

    # Verify north through car: total count = 60, total observed duration = 1800.0s (30 min)
    north_car = next(s for s in summary if s["approach"] == "north" and s["movement"] == "through")
    assert north_car["count"] == 60
    assert north_car["observed_duration_s"] == 1800.0
    # Hourly rate: 60 * 3600 / 1800 = 120.0 vph
    assert north_car["extrapolated_vehicles_per_hour"] == 120.0

    # Verify south left bus: total count = 5
    south_bus = next(s for s in summary if s["approach"] == "south" and s["movement"] == "left")
    assert south_bus["count"] == 5
    assert south_bus["observed_duration_s"] == 1800.0
    # Hourly rate: 5 * 3600 / 1800 = 10.0 vph
    assert south_bus["extrapolated_vehicles_per_hour"] == 10.0


def test_tp13_02_empty_bins_observed_summary() -> None:
    """TP13-06: Empty bins produce empty observed-period summary without errors."""
    summary = compute_observed_period_summary([])
    assert summary == []


def test_tp13_03_sqlite_export_database_generation(tmp_path) -> None:
    """TP13-03: Standalone SQLite export produces readable database with correct schema and rows."""
    sqlite_path = tmp_path / "export_test.sqlite"
    tables_data: dict[str, list[dict[str, Any]]] = {
        "videos": [
            {
                "video_id": "vid_sw_fixture",
                "filename": "clip.mp4",
                "path": "/data/clip.mp4",
                "sha256": "abc123sha",
                "fps_nominal": 30.0,
                "width": 1920,
                "height": 1080,
                "duration_s": 60.0,
                "frame_count": 1800,
                "variable_frame_rate": 0,
                "wall_clock_start": "2026-10-14T00:00:00Z",
                "ingested_at": "2026-10-14T00:01:00Z",
                "metadata_json": "{}",
            }
        ],
        "processing_runs": [
            {
                "run_id": "run_sw_fixture",
                "parent_run_id": None,
                "video_id": "vid_sw_fixture",
                "model_version": "v1.0",
                "config_hash": "cfg_hash_1",
                "config_json": "{}",
                "schema_version": "schema_hash_1",
                "code_version": "git_sha_1",
                "source_video_sha256": "abc123sha",
                "started_at": "2026-10-14T00:02:00Z",
                "completed_at": "2026-10-14T00:03:00Z",
                "status": "completed",
                "notes": "Software test fixture",
            }
        ],
        "traffic_volume_bins": [
            {
                "bin_id": "bin_1",
                "run_id": "run_sw_fixture",
                "video_id": "vid_sw_fixture",
                "line_id": "line_north",
                "bin_start_s": 0.0,
                "bin_duration_s": 900.0,
                "observed_duration_s": 60.0,
                "vehicle_class": "car",
                "approach": "north",
                "movement": "through",
                "count": 12,
                "extrapolated_vehicles_per_hour": 720.0,
            }
        ],
    }

    generate_sqlite_export_database(sqlite_path, tables_data)
    assert sqlite_path.is_file()

    # Query exported database directly
    conn = sqlite3.connect(str(sqlite_path))
    conn.row_factory = sqlite3.Row
    try:
        videos = conn.execute("SELECT * FROM videos").fetchall()
        assert len(videos) == 1
        assert videos[0]["video_id"] == "vid_sw_fixture"
        assert videos[0]["sha256"] == "abc123sha"

        runs = conn.execute("SELECT * FROM processing_runs").fetchall()
        assert len(runs) == 1
        assert runs[0]["run_id"] == "run_sw_fixture"
        assert runs[0]["code_version"] == "git_sha_1"

        bins = conn.execute("SELECT * FROM traffic_volume_bins").fetchall()
        assert len(bins) == 1
        assert bins[0]["count"] == 12
        assert bins[0]["extrapolated_vehicles_per_hour"] == 720.0
    finally:
        conn.close()


def test_tp13_04_manifest_provenance_retention() -> None:
    """TP13-04: Manifest preserves run_id, video SHA-256, model, config hash, schema version, code version."""
    run_meta = {
        "run_id": "run_provenance_test",
        "source_video_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "model_version": "yolov8n-custom-v2",
        "config_hash": "a1b2c3d4e5f6",
        "schema_version": "f6e5d4c3b2a1",
        "code_version": "9abcdef01234",
    }
    file_hashes = {"run_summary.json": "1111", "traffic_volume_bins.csv": "2222"}
    content_hash = "deadbeef12345678"

    manifest = build_export_manifest(
        run_metadata=run_meta,
        exported_files=file_hashes,
        content_hash=content_hash,
        export_timestamp="2026-10-14T02:00:00Z",
    )

    assert manifest["manifest_version"] == "1.0"
    assert manifest["run_id"] == "run_provenance_test"
    assert manifest["source_video_sha256"] == run_meta["source_video_sha256"]
    assert manifest["model_version"] == "yolov8n-custom-v2"
    assert manifest["config_hash"] == "a1b2c3d4e5f6"
    assert manifest["schema_version"] == "f6e5d4c3b2a1"
    assert manifest["code_version"] == "9abcdef01234"
    assert manifest["content_hash"] == content_hash
    assert manifest["export_timestamp"] == "2026-10-14T02:00:00Z"
    assert manifest["exported_files"] == {"run_summary.json": "1111", "traffic_volume_bins.csv": "2222"}


def test_tp13_05_content_hash_excludes_export_timestamp() -> None:
    """TP13-05: Content hash computation strictly excludes export_timestamp ensuring deterministic hashing."""
    data_1 = {
        "run_metadata": {"run_id": "run_deterministic", "status": "completed"},
        "counts": [1, 2, 3],
        "export_timestamp": "2026-10-14T01:00:00Z",
    }
    data_2 = {
        "run_metadata": {"run_id": "run_deterministic", "status": "completed"},
        "counts": [1, 2, 3],
        "export_timestamp": "2026-10-14T09:59:59Z",  # Different timestamp
    }

    hash_1 = compute_content_hash(data_1)
    hash_2 = compute_content_hash(data_2)

    assert hash_1 == hash_2
    assert len(hash_1) == 64  # Valid SHA-256 hex string


def test_tp13_11_null_research_values_not_zero() -> None:
    """TP13-11: Missing research values (null) are never substituted with zero."""
    rows = [{"speed_kmh": None, "queue_length_m": None, "count": 0}]
    csv_out = format_csv_data(rows, ["speed_kmh", "queue_length_m", "count"])
    lines = csv_out.strip().split("\n")
    # NULL speed and queue are empty string, count 0 is preserved as "0"
    assert lines[1] == ",,0"
