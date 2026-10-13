"""FastAPI endpoint and static frontend tests for Phase 13 Dashboard (TP13-13..TP13-15)."""

from __future__ import annotations

import asyncio
from pathlib import Path
import httpx
import pytest

from backend.app import create_app
from backend.database.connection import bootstrap_database
from backend.database.repository import (
    insert_counting_line,
    insert_manual_review,
    insert_queue_events,
    insert_run,
    insert_speed_observations,
    insert_stop_events,
    insert_tracks,
    insert_traffic_volume_bins,
    insert_video,
    insert_zone,
)


@pytest.fixture
def client_with_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "test_api.sqlite3"
    bootstrap_database(db_path)

    # Populate test database fixture
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    insert_video(
        conn,
        {
            "video_id": "vid_api_fixture",
            "filename": "camera_01.mp4",
            "path": "data/raw/camera_01.mp4",
            "sha256": "112233445566778899aabbccddeeff00112233445566778899aabbccddeeff00",
            "fps_nominal": 30.0,
            "width": 1920,
            "height": 1080,
            "duration_s": 60.0,
            "frame_count": 1800,
            "variable_frame_rate": 0,
            "wall_clock_start": "2026-10-14T01:00:00Z",
            "ingested_at": "2026-10-14T01:01:00Z",
            "metadata_json": "{}",
        },
    )

    insert_counting_line(
        conn,
        {
            "line_id": "line_main",
            "video_id": "vid_api_fixture",
            "name": "Main Counting Line",
            "approach": "north",
            "geometry_json": '{"x1": 0, "y1": 500, "x2": 1920, "y2": 500}',
            "bidirectional": 0,
            "config_version": "v1.0",
            "geometry_sha256": "line_api_hash",
        },
    )

    insert_zone(
        conn,
        {
            "zone_id": "zone_1",
            "video_id": "vid_api_fixture",
            "name": "North Queue Zone",
            "zone_type": "queue",
            "approach": "north",
            "geometry_json": "[[0, 0], [100, 0], [100, 100], [0, 100]]",
            "config_version": "v1.0",
            "geometry_sha256": "zone_api_hash",
        },
    )

    insert_run(
        conn,
        {
            "run_id": "run_api_test",
            "parent_run_id": None,
            "video_id": "vid_api_fixture",
            "model_version": None,
            "config_hash": "cfg_api_hash",
            "config_json": "{}",
            "schema_version": "schema_api_hash",
            "code_version": "code_api_hash",
            "source_video_sha256": "112233445566778899aabbccddeeff00112233445566778899aabbccddeeff00",
            "started_at": "2026-10-14T01:02:00Z",
            "status": "completed",
            "notes": "API test run",
        },
    )

    insert_tracks(
        conn,
        [
            {
                "track_observation_id": "trk_obs_1",
                "run_id": "run_api_test",
                "video_id": "vid_api_fixture",
                "track_id": 101,
                "frame_number": 1,
                "timestamp_s": 0.033,
                "vehicle_class": "car",
                "confidence": 0.95,
                "x1": 50, "y1": 50, "x2": 150, "y2": 150,
                "ground_x": 100, "ground_y": 150,
                "world_x": None, "world_y": None,
                "calibration_id": None,
                "trajectory_status": "complete",
            }
        ],
    )

    insert_traffic_volume_bins(
        conn,
        [
            {
                "bin_id": "bin_api_1",
                "run_id": "run_api_test",
                "video_id": "vid_api_fixture",
                "line_id": "line_main",
                "bin_start_s": 0.0,
                "bin_duration_s": 900.0,
                "observed_duration_s": 60.0,
                "vehicle_class": "car",
                "approach": "north",
                "movement": "through",
                "count": 14,
                "extrapolated_vehicles_per_hour": 840.0,
            }
        ],
    )

    conn.execute(
        """
        INSERT INTO calibration_runs (
            calibration_id, run_id, video_id, method, point_count,
            held_out_point_count, reprojection_error_m_mean,
            reprojection_error_m_max, distortion_checked, flat_road_assumption,
            accepted, parameters_json
        ) VALUES (
            'calib_api_fixture', 'run_api_test', 'vid_api_fixture', 'planar_homography',
            6, 2, 0.35, 0.58, 0, 1, 1, '{\"h\": []}'
        )
        """
    )
    insert_speed_observations(
        conn,
        [
            {
                "speed_observation_id": "spd_api_1",
                "run_id": "run_api_test",
                "video_id": "vid_api_fixture",
                "track_id": 101,
                "timestamp_s": 0.033,
                "speed_mps": 10.0,
                "speed_kmh": 36.0,
                "calibration_id": "calib_api_fixture",
                "status": "valid",
                "smoothing_window": 0.5,
                "ground_point_method": "bottom_center",
            }
        ],
    )

    insert_stop_events(
        conn,
        [
            {
                "stop_event_id": "stop_api_1",
                "run_id": "run_api_test",
                "video_id": "vid_api_fixture",
                "track_id": 101,
                "start_timestamp_s": 2.0,
                "end_timestamp_s": 5.0,
                "duration_s": 3.0,
                "threshold_kmh": 5.0,
                "status": "valid",
            }
        ],
    )

    insert_queue_events(
        conn,
        [
            {
                "queue_event_id": "q_api_1",
                "run_id": "run_api_test",
                "video_id": "vid_api_fixture",
                "zone_id": "zone_1",
                "approach": "north",
                "timestamp_s": 3.0,
                "queue_length_m": 8.5,
                "queued_vehicle_count": 2,
                "status": "valid",
            }
        ],
    )

    insert_manual_review(
        conn,
        {
            "review_id": "rev_api_1",
            "run_id": "run_api_test",
            "video_id": "vid_api_fixture",
            "track_id": 101,
            "detection_id": None,
            "frame_number": 1,
            "timestamp_s": 0.033,
            "original_class": "car",
            "corrected_class": "car",
            "original_bbox_json": None,
            "corrected_bbox_json": None,
            "reason": "routine_audit",
            "review_status": "approved",
            "reviewer": "qa_tester",
            "reviewed_at": "2026-10-14T01:05:00Z",
            "snippet_path": None,
        },
    )

    conn.commit()
    conn.close()

    # Monkeypatch config to use test database path
    from backend import config
    orig_load_config = config.load_config

    def patched_load_config(*args, **kwargs):
        cfg = orig_load_config(*args, **kwargs)
        cfg["paths"]["database_path"] = str(db_path)
        cfg["export"]["output_dir"] = str(tmp_path / "api_exports")
        return cfg

    monkeypatch.setattr(config, "load_config", patched_load_config)
    monkeypatch.setattr("backend.services.dashboard.load_config", patched_load_config)
    monkeypatch.setattr("backend.services.export.load_config", patched_load_config)


def _get(app, path: str) -> httpx.Response:
    async def req() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.get(path)
    return asyncio.run(req())


def _post(app, path: str, json_data: dict | None = None) -> httpx.Response:
    async def req() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            return await client.post(path, json=json_data or {})
    return asyncio.run(req())


def test_tp13_13_dashboard_read_only_api_endpoints(client_with_db) -> None:
    """TP13-13: Read-only JSON API endpoints return valid research payloads and schemas."""
    app = create_app()

    # 1. Runs list
    r_runs = _get(app, "/api/runs")
    assert r_runs.status_code == 200
    runs = r_runs.json()
    assert len(runs) >= 1
    assert any(r["run_id"] == "run_api_test" for r in runs)

    # 2. Run summary
    r_sum = _get(app, "/api/runs/run_api_test/summary")
    assert r_sum.status_code == 200
    summary = r_sum.json()
    assert summary["run_id"] == "run_api_test"
    assert "validation_status" in summary
    assert summary["validation_status"]["counting"] == "valid"
    assert summary["validation_status"]["speed"] == "valid"

    # 3. Volume bins
    r_bins = _get(app, "/api/runs/run_api_test/volume-bins")
    assert r_bins.status_code == 200
    bins_data = r_bins.json()
    assert len(bins_data["bins"]) == 1
    assert bins_data["bins"][0]["count"] == 14

    # 4. Tracking quality
    r_tq = _get(app, "/api/runs/run_api_test/tracking-quality")
    assert r_tq.status_code == 200
    tq = r_tq.json()
    assert tq["total_tracks"] == 1
    assert tq["total_observations"] == 1

    # 5. Speed summary
    r_spd = _get(app, "/api/runs/run_api_test/speed-summary")
    assert r_spd.status_code == 200
    spd = r_spd.json()
    assert spd["mean_speed_kmh"] == 36.0
    assert spd["valid_count"] == 1

    # 6. Queue summary
    r_que = _get(app, "/api/runs/run_api_test/queue-summary")
    assert r_que.status_code == 200
    que = r_que.json()
    assert que["stops"]["total"] == 1
    assert que["queues"]["total"] == 1

    # 7. Review status
    r_rev = _get(app, "/api/runs/run_api_test/review-status")
    assert r_rev.status_code == 200
    rev = r_rev.json()
    assert rev["total_reviews"] == 1
    assert rev["approved_count"] == 1

    # 8. Video metadata
    r_vm = _get(app, "/api/runs/run_api_test/video-metadata")
    assert r_vm.status_code == 200
    vm = r_vm.json()
    assert vm["video_id"] == "vid_api_fixture"
    assert vm["width"] == 1920

    # 9. Ground truth (unavailable when not configured)
    r_gt = _get(app, "/api/runs/run_api_test/ground-truth")
    assert r_gt.status_code == 200
    gt = r_gt.json()
    assert gt["status"] == "unavailable"

    # 10. Non-existent run returns 404
    r_404 = _get(app, "/api/runs/non_existent_run_id/summary")
    assert r_404.status_code == 404


def test_tp13_14_export_trigger_endpoint(client_with_db) -> None:
    """TP13-14: POST /api/runs/{run_id}/export triggers deterministic export."""
    app = create_app()
    resp = _post(app, "/api/runs/run_api_test/export", {"format": "all", "include_raw": True})
    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == "run_api_test"
    assert "manifest" in data
    assert "content_hash" in data


def test_tp13_15_static_frontend_served_with_required_panels() -> None:
    """TP13-15: Static frontend served at / with all required panel IDs and clean status preserves /health and /status."""
    app = create_app()

    # 1. Health and status still return phase 01 contracts
    r_health = _get(app, "/health")
    assert r_health.status_code == 200
    assert r_health.json()["phase"] == "01"

    r_status = _get(app, "/status")
    assert r_status.status_code == 200
    assert r_status.json()["implementation_scope"] == "phase_01_foundation"

    # 2. Root GET / returns static index.html
    r_root = _get(app, "/")
    assert r_root.status_code == 200
    assert "text/html" in r_root.headers.get("content-type", "")
    html = r_root.text

    # Required panel and selector IDs
    required_ids = [
        "run-selector",
        "video-metadata",
        "panel-video-metadata",
        "validation-status",
        "panel-validation-status",
        "tracking-quality",
        "panel-tracking-quality",
        "counts-bins",
        "panel-counts-bins",
        "volume-bins",
        "volume-chart",
        "speed-summary",
        "panel-speed-summary",
        "queue-stop-events",
        "panel-queue-summary",
        "queue-summary",
        "review-status",
        "panel-review-status",
        "ground-truth-comparison",
        "panel-ground-truth",
        "btn-export",
    ]
    for required_id in required_ids:
        assert f'id="{required_id}"' in html, f"Missing required panel/control ID: {required_id}"

    # Required status badge labels in HTML or classes
    assert "status-valid" in html
    assert "status-invalid" in html
    assert "status-unavailable" in html
    assert "status-unvalidated" in html

    # 3. Static assets served
    r_css = _get(app, "/style.css")
    assert r_css.status_code == 200

    r_js = _get(app, "/app.js")
    assert r_js.status_code == 200
