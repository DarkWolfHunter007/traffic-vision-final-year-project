"""Dashboard query service for Phase 13 status-aware research dashboard."""

from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any, Mapping

from backend.config import load_config
from backend.database.connection import database_connection
from backend.database.repository import (
    fetch_all_runs,
    fetch_run_by_id,
    fetch_run_export_data,
    fetch_tracking_quality_stats,
    fetch_video_for_run,
)
from backend.export import compute_observed_period_summary
from backend.services.counting import compare_counts


def _resolve_db_path(config: Mapping[str, Any] | None, repository_root: Path | None) -> Path:
    cfg = config or load_config()
    db_path = Path(cfg.get("paths", {}).get("database_path", "data/processed/traffic_vision.sqlite3"))
    if not db_path.is_absolute() and repository_root:
        db_path = repository_root / db_path
    return db_path


def ground_truth_status(report: Mapping[str, Any]) -> str:
    """Headline badge: 'valid' when the TOTAL percent error is within tolerance, else 'out_of_tolerance'.

    This matches ``services.evaluation`` (``tolerance_met`` uses the total only). Individual
    comparison rows over tolerance are flagged separately via ``annotate_row_tolerance``
    (``within_tolerance`` per row) and do not change the headline status.
    """
    tol = float(report.get("error_tolerance_pct", 10.0))
    err = report.get("total_percent_error")
    if err is None or float(err) > tol:
        return "out_of_tolerance"
    return "valid"


def annotate_row_tolerance(report: Mapping[str, Any]) -> None:
    """Add a per-row ``within_tolerance`` flag (None when the row error is unavailable)."""
    tol = float(report.get("error_tolerance_pct", 10.0))
    for row in report.get("comparisons", []) or []:
        err = row.get("percent_error")
        row["within_tolerance"] = None if err is None else float(err) <= tol


def get_dashboard_runs(
    config: Mapping[str, Any] | None = None,
    repository_root: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """List all available processing runs for the dashboard run selector."""
    def _execute(conn: sqlite3.Connection) -> list[dict[str, Any]]:
        rows = fetch_all_runs(conn)
        return [dict(r) for r in rows]

    if connection is not None:
        return _execute(connection)

    cfg = config or load_config()
    db_path = _resolve_db_path(cfg, repository_root)
    with database_connection(db_path) as conn:
        return _execute(conn)


def get_dashboard_run_summary(
    run_id: str,
    config: Mapping[str, Any] | None = None,
    repository_root: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Retrieve complete aggregate research summary and status indicators for a run."""
    def _execute(conn: sqlite3.Connection) -> dict[str, Any]:
        data = fetch_run_export_data(conn, run_id, include_raw=False)
        if data is None:
            raise ValueError(f"Processing run '{run_id}' not found")

        run_info = data["run"]
        video_info = data["video"] or {}
        volume_bins = data["traffic_volume_bins"]
        tracking_quality = data["tracking_quality"]
        speed_stats = data["speed_stats"]
        queue_stats = data["queue_stats"]
        review_stats = data["review_stats"]
        calibration = data["calibration"]

        observed_summary = compute_observed_period_summary(volume_bins)
        total_counts = sum(int(b.get("count", 0)) for b in volume_bins)

        # Build validation status indicator summary
        # Calibration status
        if calibration:
            cal_status = "valid" if calibration.get("accepted") == 1 else "invalid"
        else:
            cal_status = "unavailable"

        # Tracking status
        trk_status = "valid" if tracking_quality.get("total_tracks", 0) > 0 else "unavailable"

        # Speed status
        if speed_stats.get("total_observations", 0) > 0:
            if speed_stats.get("valid_count", 0) > 0:
                spd_status = "valid"
            elif speed_stats.get("invalid_count", 0) > 0:
                spd_status = "invalid"
            else:
                spd_status = "unavailable"
        else:
            spd_status = "unavailable"

        # Queue status
        if queue_stats.get("stops", {}).get("total", 0) > 0 or queue_stats.get("queues", {}).get("total", 0) > 0:
            que_status = "valid"
        else:
            que_status = "unavailable"

        # Counting status
        cnt_status = "valid" if len(volume_bins) > 0 else "unavailable"

        # Ground truth check
        gt_status = "unvalidated"
        gt_report = None
        try:
            gt_report = compare_counts(run_id, config=config, repository_root=repository_root, connection=conn)
            annotate_row_tolerance(gt_report)
            gt_status = ground_truth_status(gt_report)
        except (ValueError, KeyError):
            gt_status = "unavailable"

        return {
            "run_id": run_id,
            "run_metadata": run_info,
            "video_metadata": video_info,
            "validation_status": {
                "calibration": cal_status,
                "tracking": trk_status,
                "speed": spd_status,
                "queue": que_status,
                "counting": cnt_status,
                "ground_truth": gt_status,
            },
            "tracking_quality": tracking_quality,
            "volume_summary": {
                "total_vehicles_counted": total_counts,
                "total_bins": len(volume_bins),
                "observed_period_duration_s": (
                    observed_summary[0]["observed_duration_s"] if observed_summary else 0.0
                ),
            },
            "speed_summary": speed_stats,
            "queue_summary": queue_stats,
            "review_status": review_stats,
            "ground_truth_summary": gt_report,
            "calibration": calibration,
        }

    if connection is not None:
        return _execute(connection)

    cfg = config or load_config()
    db_path = _resolve_db_path(cfg, repository_root)
    with database_connection(db_path) as conn:
        return _execute(conn)


def get_dashboard_volume_bins(
    run_id: str,
    config: Mapping[str, Any] | None = None,
    repository_root: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Retrieve 15-minute volume bins and observed-period summary."""
    def _execute(conn: sqlite3.Connection) -> dict[str, Any]:
        data = fetch_run_export_data(conn, run_id, include_raw=False)
        if data is None:
            raise ValueError(f"Processing run '{run_id}' not found")
        volume_bins = data["traffic_volume_bins"]
        observed_summary = compute_observed_period_summary(volume_bins)
        return {
            "run_id": run_id,
            "bins": volume_bins,
            "observed_period_summary": observed_summary,
            "total_bins": len(volume_bins),
        }

    if connection is not None:
        return _execute(connection)

    cfg = config or load_config()
    db_path = _resolve_db_path(cfg, repository_root)
    with database_connection(db_path) as conn:
        return _execute(conn)


def get_dashboard_tracking_quality(
    run_id: str,
    config: Mapping[str, Any] | None = None,
    repository_root: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Retrieve tracking quality statistics."""
    def _execute(conn: sqlite3.Connection) -> dict[str, Any]:
        run = fetch_run_by_id(conn, run_id)
        if run is None:
            raise ValueError(f"Processing run '{run_id}' not found")
        stats = fetch_tracking_quality_stats(conn, run_id)
        return {"run_id": run_id, **stats}

    if connection is not None:
        return _execute(connection)

    cfg = config or load_config()
    db_path = _resolve_db_path(cfg, repository_root)
    with database_connection(db_path) as conn:
        return _execute(conn)


def get_dashboard_speed_summary(
    run_id: str,
    config: Mapping[str, Any] | None = None,
    repository_root: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Retrieve speed observations summary."""
    def _execute(conn: sqlite3.Connection) -> dict[str, Any]:
        data = fetch_run_export_data(conn, run_id, include_raw=False)
        if data is None:
            raise ValueError(f"Processing run '{run_id}' not found")
        return {"run_id": run_id, **data["speed_stats"]}

    if connection is not None:
        return _execute(connection)

    cfg = config or load_config()
    db_path = _resolve_db_path(cfg, repository_root)
    with database_connection(db_path) as conn:
        return _execute(conn)


def get_dashboard_queue_summary(
    run_id: str,
    config: Mapping[str, Any] | None = None,
    repository_root: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Retrieve stopped vehicle and queue event summary."""
    def _execute(conn: sqlite3.Connection) -> dict[str, Any]:
        data = fetch_run_export_data(conn, run_id, include_raw=False)
        if data is None:
            raise ValueError(f"Processing run '{run_id}' not found")
        return {"run_id": run_id, **data["queue_stats"]}

    if connection is not None:
        return _execute(connection)

    cfg = config or load_config()
    db_path = _resolve_db_path(cfg, repository_root)
    with database_connection(db_path) as conn:
        return _execute(conn)


def get_dashboard_review_status(
    run_id: str,
    config: Mapping[str, Any] | None = None,
    repository_root: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Retrieve manual review summary counts."""
    def _execute(conn: sqlite3.Connection) -> dict[str, Any]:
        data = fetch_run_export_data(conn, run_id, include_raw=False)
        if data is None:
            raise ValueError(f"Processing run '{run_id}' not found")
        return {"run_id": run_id, **data["review_stats"]}

    if connection is not None:
        return _execute(connection)

    cfg = config or load_config()
    db_path = _resolve_db_path(cfg, repository_root)
    with database_connection(db_path) as conn:
        return _execute(conn)


def get_dashboard_video_metadata(
    run_id: str,
    config: Mapping[str, Any] | None = None,
    repository_root: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Retrieve technical video metadata for the run's input video."""
    def _execute(conn: sqlite3.Connection) -> dict[str, Any]:
        v_row = fetch_video_for_run(conn, run_id)
        if v_row is None:
            raise ValueError(f"Video metadata not found for run '{run_id}'")
        return dict(v_row)

    if connection is not None:
        return _execute(connection)

    cfg = config or load_config()
    db_path = _resolve_db_path(cfg, repository_root)
    with database_connection(db_path) as conn:
        return _execute(conn)


def get_dashboard_ground_truth(
    run_id: str,
    config: Mapping[str, Any] | None = None,
    repository_root: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Retrieve ground-truth comparison report if reference counts exist."""
    def _execute(conn: sqlite3.Connection) -> dict[str, Any]:
        run = fetch_run_by_id(conn, run_id)
        if run is None:
            raise ValueError(f"Processing run '{run_id}' not found")
        try:
            report = compare_counts(run_id, config=config, repository_root=repository_root, connection=conn)
            annotate_row_tolerance(report)
            return {"run_id": run_id, "status": ground_truth_status(report), "report": report}
        except (ValueError, KeyError) as err:
            return {
                "run_id": run_id,
                "status": "unavailable",
                "message": str(err),
                "report": None,
            }

    if connection is not None:
        return _execute(connection)

    cfg = config or load_config()
    db_path = _resolve_db_path(cfg, repository_root)
    with database_connection(db_path) as conn:
        return _execute(conn)
