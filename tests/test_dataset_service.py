"""Phase 11 integration tests for active-learning dataset service, database persistence, and CLI.

All fixtures in this module are synthetic software fixtures, explicitly labelled as such.
No real-world research measurements or calibration points are fabricated.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import subprocess
from typing import Any
from uuid import uuid4

import cv2
import numpy as np
import pytest

from backend.cli import build_parser, main
from backend.config import load_config
from backend.database.connection import (
    bootstrap_database,
    database_connection,
)
from backend.database.repository import (
    fetch_approved_manual_reviews,
    fetch_ground_truth_segments,
    fetch_video_by_id,
    insert_ground_truth_counts,
    insert_ground_truth_set,
    insert_manual_review,
    insert_run,
    insert_video,
    insert_video_segments,
)
from backend.services.dataset import (
    audit_dataset_leakage_from_path,
    build_active_learning_dataset,
    get_dataset_manifest,
)
from backend.services.ingestion import _utc_now


@pytest.fixture
def synthetic_dataset_video(tmp_path: Path) -> Path:
    """Create a minimal synthetic 10-frame MP4 video as a software test fixture."""
    vid_path = tmp_path / "synthetic_dataset_video.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(vid_path), fourcc, 10.0, (640, 480))
    for i in range(10):
        frame = np.full((480, 640, 3), (i * 25, 120, 180), dtype=np.uint8)
        writer.write(frame)
    writer.release()
    return vid_path


@pytest.fixture
def dataset_test_env(tmp_path: Path, synthetic_dataset_video: Path) -> dict[str, Any]:
    """Set up database with synthetic video, processing run, and manual review records."""
    db_path = tmp_path / "dataset_test.sqlite3"
    bootstrap_database(db_path)

    video_id = "vid_synthetic_dataset_fixture"
    video_sha = "synthetic_video_sha256_dataset_fixture"
    run_id = str(uuid4())

    config = load_config()
    config["paths"]["database_path"] = str(db_path)
    config["active_learning"]["output_dir"] = str(tmp_path / "exported_datasets")

    now = _utc_now()
    repo_root = Path(__file__).resolve().parents[1]

    with database_connection(db_path) as conn:
        insert_video(
            conn,
            {
                "video_id": video_id,
                "filename": "synthetic_dataset_video.mp4",
                "path": str(synthetic_dataset_video),
                "sha256": video_sha,
                "fps_nominal": 10.0,
                "width": 640,
                "height": 480,
                "duration_s": 1.0,
                "frame_count": 10,
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
                "source_video_sha256": video_sha,
                "started_at": now,
                "status": "completed",
                "notes": "Synthetic parent run for dataset export test",
            },
        )

        # 1. Approved review on frame 1 (corrected class and bbox)
        insert_manual_review(
            conn,
            {
                "review_id": "rev_approved_01",
                "run_id": run_id,
                "video_id": video_id,
                "track_id": 1,
                "detection_id": "det_01",
                "frame_number": 1,
                "timestamp_s": 0.1,
                "original_class": "car",
                "corrected_class": "auto_rickshaw",
                "original_bbox_json": json.dumps({"x1": 50, "y1": 50, "x2": 150, "y2": 150}),
                "corrected_bbox_json": json.dumps({"x1": 60, "y1": 60, "x2": 160, "y2": 160}),
                "reason": "class_ambiguity",
                "review_status": "approved",
                "reviewer": "expert_analyst",
                "reviewed_at": now,
                "snippet_path": None,
            },
        )

        # 2. Approved review on frame 2 (no correction, original approved)
        insert_manual_review(
            conn,
            {
                "review_id": "rev_approved_02",
                "run_id": run_id,
                "video_id": video_id,
                "track_id": 2,
                "detection_id": "det_02",
                "frame_number": 2,
                "timestamp_s": 0.2,
                "original_class": "bus",
                "corrected_class": None,
                "original_bbox_json": json.dumps({"x1": 100, "y1": 100, "x2": 300, "y2": 300}),
                "corrected_bbox_json": None,
                "reason": "low_confidence",
                "review_status": "approved",
                "reviewer": "expert_analyst",
                "reviewed_at": now,
                "snippet_path": None,
            },
        )

        # 3. Pending review on frame 3 (MUST be excluded)
        insert_manual_review(
            conn,
            {
                "review_id": "rev_pending_03",
                "run_id": run_id,
                "video_id": video_id,
                "track_id": 3,
                "detection_id": "det_03",
                "frame_number": 3,
                "timestamp_s": 0.3,
                "original_class": "car",
                "corrected_class": "truck",
                "original_bbox_json": json.dumps({"x1": 200, "y1": 200, "x2": 300, "y2": 300}),
                "corrected_bbox_json": None,
                "reason": "boundary_drift",
                "review_status": "pending",
                "reviewer": "junior_reviewer",
                "reviewed_at": now,
                "snippet_path": None,
            },
        )

        # 4. Rejected review on frame 4 (MUST be excluded)
        insert_manual_review(
            conn,
            {
                "review_id": "rev_rejected_04",
                "run_id": run_id,
                "video_id": video_id,
                "track_id": 4,
                "detection_id": "det_04",
                "frame_number": 4,
                "timestamp_s": 0.4,
                "original_class": "motorcycle",
                "corrected_class": "car",
                "original_bbox_json": json.dumps({"x1": 10, "y1": 10, "x2": 50, "y2": 50}),
                "corrected_bbox_json": None,
                "reason": "manual_flag",
                "review_status": "rejected",
                "reviewer": "auditor",
                "reviewed_at": now,
                "snippet_path": None,
            },
        )

    return {
        "db_path": db_path,
        "video_id": video_id,
        "run_id": run_id,
        "config": config,
        "repo_root": repo_root,
        "tmp_path": tmp_path,
    }


def test_tp11_03_approved_review_filtering(dataset_test_env: dict[str, Any]) -> None:
    """TP11-03: Only reviews with review_status = 'approved' are fetched for dataset construction."""
    with database_connection(dataset_test_env["db_path"]) as conn:
        approved_revs = fetch_approved_manual_reviews(conn)
        assert len(approved_revs) == 2
        rev_ids = {r["review_id"] for r in approved_revs}
        assert "rev_approved_01" in rev_ids
        assert "rev_approved_02" in rev_ids
        assert "rev_pending_03" not in rev_ids
        assert "rev_rejected_04" not in rev_ids


def test_tp11_04_and_13_end_to_end_dataset_export(dataset_test_env: dict[str, Any]) -> None:
    """TP11-04 & TP11-13: Correction resolution and end-to-end dataset generation service."""
    result = build_active_learning_dataset(
        dataset_version="test_v1",
        config=dataset_test_env["config"],
        repository_root=dataset_test_env["repo_root"],
    )

    assert result["dataset_version"] == "test_v1"
    assert result["total_samples"] == 2
    assert result["total_boxes"] == 2

    ds_dir = Path(result["dataset_dir"])
    assert ds_dir.exists()
    assert (ds_dir / "dataset.yaml").exists()
    assert (ds_dir / "manifest.json").exists()

    # Verify TP11-04: Human correction took precedence for rev_approved_01
    manifest = get_dataset_manifest(ds_dir)
    samples = manifest["samples"]
    sample_f1 = next(s for s in samples if s["frame_number"] == 1)
    assert sample_f1["review_ids"] == ["rev_approved_01"]
    assert sample_f1["reviewers"] == ["expert_analyst"]
    # Check that corrected_class 'auto_rickshaw' (id=4 in class_mapping) was exported
    assert len(sample_f1["annotations"]) == 1
    assert sample_f1["annotations"][0]["class_id"] == 4

    # Verify rev_approved_02: Original class 'bus' (id=1 in class_mapping) was exported
    sample_f2 = next(s for s in samples if s["frame_number"] == 2)
    assert sample_f2["annotations"][0]["class_id"] == 1

    # Verify images and labels exist on disk
    split_f1 = sample_f1["split"]
    assert (ds_dir / sample_f1["image_rel_path"]).exists()
    assert (ds_dir / sample_f1["label_rel_path"]).exists()

    # Verify label file content
    label_txt = (ds_dir / sample_f1["label_rel_path"]).read_text(encoding="utf-8")
    assert label_txt.startswith("4 ")  # auto_rickshaw class_id


def test_tp11_11_manifest_provenance_verification(dataset_test_env: dict[str, Any]) -> None:
    """TP11-11: manifest.json records source video SHA-256, frame, run_id, and reviewer."""
    result = build_active_learning_dataset(
        dataset_version="test_provenance_v1",
        config=dataset_test_env["config"],
        repository_root=dataset_test_env["repo_root"],
    )

    manifest_path = Path(result["manifest_path"])
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest_data["dataset_version"] == "test_provenance_v1"
    assert "config_hash" in manifest_data
    assert "code_version" in manifest_data
    assert manifest_data["total_samples"] == 2

    sample = manifest_data["samples"][0]
    assert sample["video_id"] == dataset_test_env["video_id"]
    assert sample["source_video_sha256"] == "synthetic_video_sha256_dataset_fixture"
    assert sample["run_id"] == dataset_test_env["run_id"]
    assert "frame_number" in sample
    assert "timestamp_s" in sample
    assert "reviewer" in sample["reviewers"][0] or len(sample["reviewers"]) > 0
    assert "reviewed_at" in sample


def test_tp11_14_cli_dataset_commands(
    dataset_test_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """TP11-14: CLI export-dataset, show-dataset-manifest, and audit-dataset-leakage."""
    cfg_file = dataset_test_env["tmp_path"] / "cli_test_config.yaml"
    import yaml
    cfg_file.write_text(yaml.dump(dataset_test_env["config"]), encoding="utf-8")

    # 1. Test export-dataset CLI
    export_args = [
        "traffic-vision",
        "export-dataset",
        "--version", "cli_v1",
        "--config", str(cfg_file),
    ]
    monkeypatch.setattr("sys.argv", export_args)
    main()
    captured_export = capsys.readouterr()
    res_json = json.loads(captured_export.out)
    assert res_json["dataset_version"] == "cli_v1"
    assert res_json["total_samples"] == 2

    # 2. Test show-dataset-manifest CLI
    manifest_path = res_json["manifest_path"]
    show_args = [
        "traffic-vision",
        "show-dataset-manifest",
        str(manifest_path),
        "--config", str(cfg_file),
    ]
    monkeypatch.setattr("sys.argv", show_args)
    main()
    captured_show = capsys.readouterr()
    man_json = json.loads(captured_show.out)
    assert man_json["dataset_version"] == "cli_v1"
    assert man_json["total_samples"] == 2

    # 3. Test audit-dataset-leakage CLI
    audit_args = [
        "traffic-vision",
        "audit-dataset-leakage",
        str(manifest_path),
        "--config", str(cfg_file),
    ]
    monkeypatch.setattr("sys.argv", audit_args)
    main()
    captured_audit = capsys.readouterr()
    audit_json = json.loads(captured_audit.out)
    assert audit_json["is_leakage_safe"] is True
    assert audit_json["group_leakage_detected"] is False


def test_tp11_ground_truth_segment_protection_service(
    dataset_test_env: dict[str, Any], tmp_path: Path
) -> None:
    """Verify that video segments marked with ground truth counts never enter 'train' split."""
    db_path = dataset_test_env["db_path"]
    vid_id = dataset_test_env["video_id"]

    # Insert a video_segment covering frame 1 (t=0.1s) and mark it as ground truth
    with database_connection(db_path) as conn:
        insert_video_segments(
            conn,
            [
                {
                    "segment_id": "seg_gt_eval_01",
                    "video_id": vid_id,
                    "start_s": 0.0,
                    "end_s": 0.15,
                    "start_frame": 0,
                    "end_frame": 1,
                    "label": "ground_truth_eval_clip",
                    "condition_notes": "Software test fixture for GT protection",
                }
            ],
        )
        insert_ground_truth_set(
            conn,
            {
                "ground_truth_set_id": "gt_set_fixture_01",
                "name": "Synthetic GT Count Set",
                "source_description": "Manual count ground truth fixture",
                "split_group": "eval_held_out",
                "created_at": _utc_now(),
            },
        )
        insert_ground_truth_counts(
            conn,
            [
                {
                    "ground_truth_count_id": "gtc_01",
                    "ground_truth_set_id": "gt_set_fixture_01",
                    "video_segment_id": "seg_gt_eval_01",
                    "approach": "north",
                    "movement": "through",
                    "vehicle_class": "car",
                    "observed_count": 5,
                }
            ],
        )

    # Export dataset with 100% train ratio requested
    result = build_active_learning_dataset(
        dataset_version="test_gt_protected",
        split_ratios={"train": 1.0, "val": 0.0, "test": 0.0},
        config=dataset_test_env["config"],
        repository_root=dataset_test_env["repo_root"],
    )

    manifest = get_dataset_manifest(result["dataset_dir"])
    sample_f1 = next(s for s in manifest["samples"] if s["frame_number"] == 1)

    # Frame 1 is within ground truth segment [0.0, 0.15], so it MUST NOT be assigned to 'train'
    assert sample_f1["is_ground_truth_clip"] is True
    assert sample_f1["split"] != "train"
    assert sample_f1["split"] == "val"
