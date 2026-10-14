"""Integration tests for Phase 10 FastAPI review endpoints.

Software fixture notice: Test fixtures are synthetic software fixtures for validating
invariants and error handling; they do not represent real-world CCTV footage validation.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import cv2
import httpx
import numpy as np
import pytest

from backend.app import create_app
from backend.config import canonical_json, config_hash, load_config
from backend.database.connection import bootstrap_database, database_connection, schema_version
from backend.database.repository import (
    insert_detections,
    insert_run,
    insert_video,
)
from backend.services.ingestion import _utc_now, current_code_version


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

    def patch(self, url: str, **kwargs: Any) -> httpx.Response:
        return self._request("patch", url, **kwargs)


@pytest.fixture
def api_test_env(tmp_path: Path) -> dict[str, Any]:
    """Create test environment for FastAPI review endpoints."""
    db_path = tmp_path / "api_test.sqlite3"
    bootstrap_database(db_path)

    # Minimal synthetic video
    vid_file = tmp_path / "api_synthetic_vid.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(vid_file), fourcc, 10.0, (640, 480))
    for i in range(5):
        frame = np.full((480, 640, 3), (i * 30, 80, 120), dtype=np.uint8)
        writer.write(frame)
    writer.release()

    video_id = "vid_api_test"
    parent_run_id = str(uuid4())

    config = load_config()
    config["paths"]["database_path"] = str(db_path)
    config["review"]["output_dir"] = str(tmp_path / "api_snippets")

    repo_root = Path(__file__).resolve().parents[1]
    now = _utc_now()

    with database_connection(db_path) as conn:
        insert_video(
            conn,
            {
                "video_id": video_id,
                "filename": "api_synthetic_vid.mp4",
                "path": str(vid_file),
                "sha256": "api_vid_sha",
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
                "run_id": parent_run_id,
                "parent_run_id": None,
                "video_id": video_id,
                "model_version": None,
                "config_hash": config_hash(config),
                "config_json": canonical_json(config),
                "schema_version": schema_version(),
                "code_version": current_code_version(repo_root),
                "source_video_sha256": "api_vid_sha",
                "started_at": now,
                "status": "completed",
                "notes": "API test run",
            },
        )
        insert_detections(
            conn,
            [
                {
                    "detection_id": "det_api_low",
                    "run_id": parent_run_id,
                    "video_id": video_id,
                    "frame_number": 2,
                    "timestamp_s": 0.2,
                    "class_id": 2,
                    "class_name": "car",
                    "confidence": 0.35,
                    "x1": 50.0,
                    "y1": 50.0,
                    "x2": 150.0,
                    "y2": 150.0,
                    "ground_x": 100.0,
                    "ground_y": 150.0,
                    "width_px": 100.0,
                    "height_px": 100.0,
                }
            ],
        )

    return {
        "db_path": db_path,
        "video_id": video_id,
        "parent_run_id": parent_run_id,
        "config": config,
        "video_file": vid_file,
    }


def test_tp10_13_fastapi_review_endpoints_crud(
    api_test_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """TP10-13: FastAPI review endpoints return typed responses with appropriate HTTP status codes."""
    cfg = api_test_env["config"]
    monkeypatch.setattr("backend.services.review.load_config", lambda *args, **kwargs: cfg)

    client = SyncApiClient(create_app())
    parent_run_id = api_test_env["parent_run_id"]

    # 1. Search candidates
    resp = client.post(
        "/reviews/candidates",
        json={"parent_run_id": parent_run_id, "confidence_threshold": 0.50},
    )
    assert resp.status_code == 200
    cands_data = resp.json()
    assert cands_data["candidate_count"] == 1
    assert cands_data["candidates"][0]["item_id"] == "det_api_low"

    # 2. Create review
    create_payload = {
        "parent_run_id": parent_run_id,
        "frame_number": 2,
        "timestamp_s": 0.2,
        "reason": "low_confidence_test",
        "detection_id": "det_api_low",
        "reviewer": "api_analyst",
        "corrected_class": "auto_rickshaw",
        "corrected_bbox": {"x1": 48.0, "y1": 48.0, "x2": 152.0, "y2": 152.0},
        "status": "pending",
        "generate_snippet": False,
    }
    resp = client.post("/reviews", json=create_payload)
    assert resp.status_code == 201
    created = resp.json()
    review_id = created["review_id"]
    assert created["review_status"] == "pending"
    assert created["corrected_class"] == "auto_rickshaw"
    assert created["reviewer"] == "api_analyst"

    # 3. Get single review
    resp = client.get(f"/reviews/{review_id}")
    assert resp.status_code == 200
    fetched = resp.json()
    assert fetched["review_id"] == review_id

    # 4. List reviews with filters
    resp = client.get("/reviews", params={"reviewer": "api_analyst"})
    assert resp.status_code == 200
    list_data = resp.json()
    assert list_data["count"] == 1
    assert list_data["reviews"][0]["review_id"] == review_id

    # 5. Patch review
    patch_payload = {
        "status": "approved",
        "reviewer": "api_lead",
    }
    resp = client.patch(f"/reviews/{review_id}", json=patch_payload)
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["review_status"] == "approved"
    assert updated["reviewer"] == "api_lead"

    # 6. Generate snippet for review
    resp = client.post(f"/reviews/{review_id}/snippet")
    assert resp.status_code == 200
    snippet_data = resp.json()
    assert snippet_data["review_id"] == review_id
    assert Path(snippet_data["snippet_path"]).is_file()


def test_tp10_14_fastapi_validation_error_responses(
    api_test_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """TP10-14: Out-of-frame boxes or invalid classes submitted to the API return 422 errors."""
    cfg = api_test_env["config"]
    monkeypatch.setattr("backend.services.review.load_config", lambda *args, **kwargs: cfg)

    client = SyncApiClient(create_app())
    parent_run_id = api_test_env["parent_run_id"]

    # Out-of-frame box (x2 = 700 > frame_width 640)
    out_of_frame_payload = {
        "parent_run_id": parent_run_id,
        "frame_number": 2,
        "timestamp_s": 0.2,
        "reason": "invalid_box_test",
        "corrected_bbox": {"x1": 50.0, "y1": 50.0, "x2": 700.0, "y2": 150.0},
    }
    resp = client.post("/reviews", json=out_of_frame_payload)
    assert resp.status_code == 422
    assert "extends beyond frame width" in resp.json()["detail"]

    # Disallowed class
    invalid_class_payload = {
        "parent_run_id": parent_run_id,
        "frame_number": 2,
        "timestamp_s": 0.2,
        "reason": "invalid_class_test",
        "corrected_class": "submarine",
    }
    resp = client.post("/reviews", json=invalid_class_payload)
    assert resp.status_code == 422
    assert "not allowed" in resp.json()["detail"]

    # 404 for non-existent review
    resp = client.get("/reviews/non_existent_id")
    assert resp.status_code == 404
