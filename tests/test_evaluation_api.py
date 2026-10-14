"""Integration tests for Phase 12 FastAPI model evaluation endpoints (TP12-15).

All fixtures in this module are synthetic software test fixtures; no real research data or CCTV measurements are fabricated.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest

from backend.app import create_app
from backend.config import load_config
from backend.database.connection import bootstrap_database, database_connection
from backend.database.repository import (
    insert_crossing_events,
    insert_ground_truth_counts,
    insert_ground_truth_set,
    insert_run,
    insert_video,
    insert_video_segments,
)
from backend.services.evaluation import register_model
from backend.services.ingestion import _utc_now


class SyncApiClient:
    """Synchronous test client wrapper using httpx.ASGITransport."""

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
def api_test_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    db_path = tmp_path / "api_test.sqlite3"
    bootstrap_database(db_path)

    weights_1 = tmp_path / "model1.pt"
    weights_1.write_bytes(b"MODEL1_BYTES_FIXTURE")

    weights_2 = tmp_path / "model2.pt"
    weights_2.write_bytes(b"MODEL2_BYTES_FIXTURE")

    eval_dir = tmp_path / "evaluations"
    eval_dir.mkdir(parents=True, exist_ok=True)

    # Synthetic dataset manifest
    manifest_data = {
        "dataset_version": "v1_test",
        "class_mapping": {"car": 0},
        "samples": [
            {
                "sample_id": "s_train_1",
                "video_id": "vid1",
                "frame_number": 1,
                "split": "train",
                "annotations": [{"class_id": 0, "x_center": 0.5, "y_center": 0.5, "width": 0.2, "height": 0.2}],
            },
            {
                "sample_id": "s_val_1",
                "video_id": "vid1",
                "frame_number": 2,
                "split": "val",
                "annotations": [{"class_id": 0, "x_center": 0.5, "y_center": 0.5, "width": 0.2, "height": 0.2}],
            },
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

    # Override config loading to point to test database and evaluation dir
    original_load = load_config

    def _mock_load_config(path: Any = None, overrides: Any = None) -> dict[str, Any]:
        cfg = original_load(path, overrides)
        cfg["paths"]["database_path"] = str(db_path)
        cfg["evaluation"]["output_dir"] = str(eval_dir)
        return cfg

    monkeypatch.setattr("backend.app.load_config", _mock_load_config)
    monkeypatch.setattr("backend.services.evaluation.load_config", _mock_load_config)

    app = create_app()
    client = SyncApiClient(app)

    return {
        "client": client,
        "db_path": db_path,
        "weights_1": weights_1,
        "weights_2": weights_2,
        "manifest_path": manifest_path,
        "tmp_path": tmp_path,
    }


def test_tp12_15_register_and_list_models_api(api_test_env: dict[str, Any]) -> None:
    client: SyncApiClient = api_test_env["client"]

    # Register model 1
    resp = client.post(
        "/models/register",
        json={
            "model_version": "api_model_v1",
            "model_path": str(api_test_env["weights_1"]),
            "dataset_version": "v1_test",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["model_version"] == "api_model_v1"
    assert data["selected_for_production"] == 0

    # Register model with non-existent path -> 422
    resp_err = client.post(
        "/models/register",
        json={
            "model_version": "api_model_missing",
            "model_path": str(api_test_env["tmp_path"] / "nonexistent.pt"),
        },
    )
    assert resp_err.status_code == 422

    # List models
    resp_list = client.get("/models")
    assert resp_list.status_code == 200
    models = resp_list.json()
    assert len(models) == 1
    assert models[0]["model_version"] == "api_model_v1"

    # Get model details
    resp_det = client.get("/models/api_model_v1")
    assert resp_det.status_code == 200
    assert resp_det.json()["model_version"] == "api_model_v1"

    # Non-existent model details -> 404
    resp_404 = client.get("/models/does_not_exist")
    assert resp_404.status_code == 404


def test_tp12_15_evaluate_detection_and_leakage_api(api_test_env: dict[str, Any]) -> None:
    client: SyncApiClient = api_test_env["client"]
    # Register model
    client.post(
        "/models/register",
        json={"model_version": "api_model_v1", "model_path": str(api_test_env["weights_1"])},
    )

    # Attempt evaluate on 'train' split -> leakage check fails (422)
    resp_leak = client.post(
        "/models/evaluate-detection",
        json={
            "model_version": "api_model_v1",
            "dataset_path": str(api_test_env["manifest_path"]),
            "split": "train",
        },
    )
    assert resp_leak.status_code == 422
    assert "Leakage check failed" in resp_leak.json()["detail"]


def test_tp12_15_compare_and_select_production_api(api_test_env: dict[str, Any]) -> None:
    client: SyncApiClient = api_test_env["client"]

    client.post(
        "/models/register",
        json={"model_version": "model_a", "model_path": str(api_test_env["weights_1"])},
    )
    client.post(
        "/models/register",
        json={"model_version": "model_b", "model_path": str(api_test_env["weights_2"])},
    )

    # Compare models
    resp_cmp = client.post(
        "/models/compare",
        json={"model_version_a": "model_a", "model_version_b": "model_b"},
    )
    assert resp_cmp.status_code == 200
    cmp_data = resp_cmp.json()
    assert cmp_data["model_version_a"] == "model_a"
    assert cmp_data["model_version_b"] == "model_b"

    # Select production model
    resp_sel = client.post(
        "/models/select-production",
        json={"model_version": "model_a"},
    )
    assert resp_sel.status_code == 200
    assert resp_sel.json()["selected_for_production"] == 1

    # Verify active production model via GET
    mod_a = client.get("/models/model_a").json()
    assert mod_a["selected_for_production"] == 1

    # Select model_b -> model_a should no longer be production
    client.post(
        "/models/select-production",
        json={"model_version": "model_b"},
    )
    mod_a_after = client.get("/models/model_a").json()
    assert mod_a_after["selected_for_production"] == 0
    mod_b_after = client.get("/models/model_b").json()
    assert mod_b_after["selected_for_production"] == 1
