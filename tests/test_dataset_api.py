"""Integration tests for Phase 11 FastAPI active-learning dataset endpoints.

Software fixture notice: Test fixtures are synthetic software fixtures for validating
invariants and error handling; they do not represent real-world CCTV footage validation.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import cv2
import httpx
import numpy as np
import pytest

from backend.app import create_app
from backend.config import load_config
from backend.database.connection import bootstrap_database, database_connection
from backend.database.repository import (
    insert_manual_review,
    insert_run,
    insert_video,
)
from backend.services.ingestion import _utc_now


class SyncApiClient:
    """Synchronous test client wrapper using httpx.ASGITransport and httpx.AsyncClient."""

    def __init__(self, app: Any) -> None:
        self.app = app

    def _request(self, method_name: str, url: str, **kwargs: Any) -> httpx.Response:
        async def _run() -> httpx.Response:
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                method = getattr(client, method_name)
                return await method(url, **kwargs)

        return asyncio.run(_run())

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self._request("get", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return self._request("post", url, **kwargs)


@pytest.fixture
def synthetic_api_video(tmp_path: Path) -> Path:
    """Create a minimal synthetic 5-frame MP4 video as a software test fixture."""
    vid_path = tmp_path / "synthetic_api_video.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(vid_path), fourcc, 10.0, (640, 480))
    for i in range(5):
        frame = np.full((480, 640, 3), (i * 30, 80, 140), dtype=np.uint8)
        writer.write(frame)
    writer.release()
    return vid_path


@pytest.fixture
def dataset_api_client(tmp_path: Path, synthetic_api_video: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[SyncApiClient, dict[str, Any]]:
    """Set up database and FastAPI test client with synthetic review fixtures."""
    db_path = tmp_path / "dataset_api_test.sqlite3"
    bootstrap_database(db_path)

    export_root = tmp_path / "api_datasets"
    export_root.mkdir(parents=True, exist_ok=True)

    config = load_config()
    config["paths"]["database_path"] = str(db_path)
    config["active_learning"]["output_dir"] = str(export_root)

    # Monkeypatch load_config so backend.app uses this test database
    monkeypatch.setattr("backend.app.load_config", lambda *args, **kwargs: config)
    monkeypatch.setattr("backend.services.dataset.load_config", lambda *args, **kwargs: config)

    video_id = "vid_api_fixture_01"
    run_id = str(uuid4())
    now = _utc_now()

    with database_connection(db_path) as conn:
        insert_video(
            conn,
            {
                "video_id": video_id,
                "filename": "synthetic_api_video.mp4",
                "path": str(synthetic_api_video),
                "sha256": "sha256_api_video_fixture",
                "fps_nominal": 10.0,
                "width": 640,
                "height": 480,
                "duration_s": 0.5,
                "frame_count": 5,
                "variable_frame_rate": 0,
                "wall_clock_start": None,
                "ingested_at": now,
                "metadata_json": "{}",
            },
        )
        insert_run(
            conn,
            {
                "run_id": run_id,
                "parent_run_id": None,
                "video_id": video_id,
                "model_version": None,
                "config_hash": "cfg_hash_synthetic",
                "config_json": "{}",
                "schema_version": "schema_ver_synthetic",
                "code_version": "code_ver_synthetic",
                "source_video_sha256": "sha256_api_video_fixture",
                "started_at": now,
                "status": "completed",
                "notes": "Synthetic parent run for API test",
            },
        )
        insert_manual_review(
            conn,
            {
                "review_id": "rev_api_approved_01",
                "run_id": run_id,
                "video_id": video_id,
                "track_id": 10,
                "detection_id": "det_api_01",
                "frame_number": 0,
                "timestamp_s": 0.0,
                "original_class": "car",
                "corrected_class": "bus",
                "original_bbox_json": json.dumps({"x1": 20, "y1": 20, "x2": 120, "y2": 120}),
                "corrected_bbox_json": json.dumps({"x1": 30, "y1": 30, "x2": 150, "y2": 150}),
                "reason": "class_ambiguity",
                "review_status": "approved",
                "reviewer": "test_analyst",
                "reviewed_at": now,
                "snippet_path": None,
            },
        )

    app = create_app()
    client = SyncApiClient(app)
    return client, {
        "db_path": db_path,
        "video_id": video_id,
        "run_id": run_id,
        "export_root": export_root,
        "config": config,
    }


def test_tp11_15_fastapi_export_dataset_endpoint(
    dataset_api_client: tuple[SyncApiClient, dict[str, Any]]
) -> None:
    """TP11-15: POST /datasets/export successfully exports dataset and returns 201 Created."""
    client, env = dataset_api_client

    response = client.post(
        "/datasets/export",
        json={
            "dataset_version": "api_v1",
            "output_dir": str(env["export_root"]),
            "export_images": True,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["dataset_version"] == "api_v1"
    assert data["total_samples"] == 1
    assert "manifest_path" in data
    assert "leakage_audit" in data
    assert data["leakage_audit"]["is_leakage_safe"] is True


def test_tp11_15_fastapi_get_manifest_endpoint(
    dataset_api_client: tuple[SyncApiClient, dict[str, Any]]
) -> None:
    """TP11-15: GET /datasets/{dataset_version}/manifest returns 200 with manifest or 404."""
    client, env = dataset_api_client

    # First export a dataset
    export_resp = client.post(
        "/datasets/export",
        json={
            "dataset_version": "api_manifest_v1",
            "output_dir": str(env["export_root"]),
            "export_images": False,
        },
    )
    assert export_resp.status_code == 201

    # Fetch manifest
    get_resp = client.get(
        "/datasets/api_manifest_v1/manifest",
        params={"output_dir": str(env["export_root"])},
    )
    assert get_resp.status_code == 200
    manifest = get_resp.json()
    assert manifest["dataset_version"] == "api_manifest_v1"
    assert manifest["total_samples"] == 1

    # Non-existent version returns 404
    missing_resp = client.get(
        "/datasets/non_existent_version_xyz/manifest",
        params={"output_dir": str(env["export_root"])},
    )
    assert missing_resp.status_code == 404


def test_tp11_15_fastapi_audit_leakage_endpoint(
    dataset_api_client: tuple[SyncApiClient, dict[str, Any]]
) -> None:
    """TP11-15: POST /datasets/audit-leakage returns leakage verification report."""
    client, env = dataset_api_client

    # Export a dataset
    export_resp = client.post(
        "/datasets/export",
        json={
            "dataset_version": "api_audit_v1",
            "output_dir": str(env["export_root"]),
            "export_images": False,
        },
    )
    assert export_resp.status_code == 201
    manifest_path = export_resp.json()["manifest_path"]

    # Audit leakage
    audit_resp = client.post(
        "/datasets/audit-leakage",
        json={"dataset_path": manifest_path},
    )
    assert audit_resp.status_code == 200
    report = audit_resp.json()
    assert report["is_leakage_safe"] is True
    assert report["group_leakage_detected"] is False

    # Non-existent path returns 404
    missing_resp = client.post(
        "/datasets/audit-leakage",
        json={"dataset_path": "/invalid/non_existent/path/manifest.json"},
    )
    assert missing_resp.status_code == 404


def test_tp11_15_fastapi_export_error_when_no_reviews(
    dataset_api_client: tuple[SyncApiClient, dict[str, Any]]
) -> None:
    """TP11-15: POST /datasets/export returns 422 if no matching approved reviews exist."""
    client, env = dataset_api_client

    response = client.post(
        "/datasets/export",
        json={
            "dataset_version": "empty_v1",
            "run_id": "non_existent_run_id_9999",
            "output_dir": str(env["export_root"]),
        },
    )
    assert response.status_code == 422
    assert "No approved manual reviews found" in response.json()["detail"]
