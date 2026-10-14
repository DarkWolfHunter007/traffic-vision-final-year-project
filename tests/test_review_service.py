"""Phase 10 integration tests for manual review service, database persistence, and CLI.

All test fixtures in this module are synthetic software fixtures, explicitly
labelled as such. No real-world research measurements or calibration points
are fabricated.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
from typing import Any
from uuid import uuid4

import cv2
import numpy as np
import pytest

from backend.cli import build_parser, main
from backend.config import canonical_json, config_hash, load_config
from backend.database.connection import (
    bootstrap_database,
    database_connection,
    schema_version,
)
from backend.database.repository import (
    fetch_detections_for_tracking,
    fetch_manual_review_by_id,
    fetch_manual_review_stats,
    fetch_manual_reviews,
    fetch_tracks_for_run,
    insert_detections,
    insert_run,
    insert_tracks,
    insert_video,
)
from backend.services.ingestion import _utc_now, current_code_version
from backend.services.review import (
    create_manual_review,
    find_review_candidates,
    generate_snippet_for_review,
    get_manual_review_by_id,
    get_manual_reviews,
    update_manual_review,
)


@pytest.fixture
def synthetic_video_file(tmp_path: Path) -> Path:
    """Create a minimal 1-second synthetic MP4 video file as a software test fixture."""
    vid_path = tmp_path / "synthetic_test_video.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(vid_path), fourcc, 10.0, (320, 240))
    for i in range(10):
        frame = np.full((240, 320, 3), (i * 20, 100, 150), dtype=np.uint8)
        writer.write(frame)
    writer.release()
    return vid_path


@pytest.fixture
def review_test_env(tmp_path: Path, synthetic_video_file: Path) -> dict[str, Any]:
    """Set up database with synthetic video, detection run, and tracking run."""
    db_path = tmp_path / "review_test.sqlite3"
    bootstrap_database(db_path)

    video_id = "vid_synthetic_review_fixture"
    parent_run_id = str(uuid4())

    config = load_config()
    config["paths"]["database_path"] = str(db_path)
    config["review"]["output_dir"] = str(tmp_path / "review_snippets")

    now = _utc_now()
    repo_root = Path(__file__).resolve().parents[1]

    with database_connection(db_path) as conn:
        insert_video(
            conn,
            {
                "video_id": video_id,
                "filename": "synthetic_test_video.mp4",
                "path": str(synthetic_video_file),
                "sha256": "synthetic_video_sha256_fixture",
                "fps_nominal": 10.0,
                "width": 320,
                "height": 240,
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
                "run_id": parent_run_id,
                "parent_run_id": None,
                "video_id": video_id,
                "model_version": None,
                "config_hash": config_hash(config),
                "config_json": canonical_json(config),
                "schema_version": schema_version(),
                "code_version": current_code_version(repo_root),
                "source_video_sha256": "synthetic_video_sha256_fixture",
                "started_at": now,
                "status": "completed",
                "notes": "Synthetic parent run for review testing",
            },
        )

        # Insert synthetic detections: 1 high-confidence, 2 low-confidence
        insert_detections(
            conn,
            [
                {
                    "detection_id": "det_high_conf",
                    "run_id": parent_run_id,
                    "video_id": video_id,
                    "frame_number": 2,
                    "timestamp_s": 0.2,
                    "class_id": 2,
                    "class_name": "car",
                    "confidence": 0.88,
                    "x1": 50.0,
                    "y1": 50.0,
                    "x2": 150.0,
                    "y2": 150.0,
                    "ground_x": 100.0,
                    "ground_y": 150.0,
                    "width_px": 100.0,
                    "height_px": 100.0,
                },
                {
                    "detection_id": "det_low_conf_1",
                    "run_id": parent_run_id,
                    "video_id": video_id,
                    "frame_number": 3,
                    "timestamp_s": 0.3,
                    "class_id": 3,
                    "class_name": "motorcycle",
                    "confidence": 0.32,
                    "x1": 60.0,
                    "y1": 60.0,
                    "x2": 120.0,
                    "y2": 140.0,
                    "ground_x": 90.0,
                    "ground_y": 140.0,
                    "width_px": 60.0,
                    "height_px": 80.0,
                },
                {
                    "detection_id": "det_low_conf_2",
                    "run_id": parent_run_id,
                    "video_id": video_id,
                    "frame_number": 5,
                    "timestamp_s": 0.5,
                    "class_id": 5,
                    "class_name": "bus",
                    "confidence": 0.45,
                    "x1": 10.0,
                    "y1": 20.0,
                    "x2": 200.0,
                    "y2": 220.0,
                    "ground_x": 105.0,
                    "ground_y": 220.0,
                    "width_px": 190.0,
                    "height_px": 200.0,
                },
            ],
        )

        # Insert synthetic track observation
        insert_tracks(
            conn,
            [
                {
                    "track_observation_id": "trk_obs_low",
                    "run_id": parent_run_id,
                    "video_id": video_id,
                    "track_id": 7,
                    "frame_number": 4,
                    "timestamp_s": 0.4,
                    "vehicle_class": "auto_rickshaw",
                    "confidence": 0.28,
                    "x1": 80.0,
                    "y1": 80.0,
                    "x2": 160.0,
                    "y2": 160.0,
                    "ground_x": 120.0,
                    "ground_y": 160.0,
                    "world_x": None,
                    "world_y": None,
                    "calibration_id": None,
                    "trajectory_status": "complete",
                }
            ],
        )

    return {
        "db_path": db_path,
        "video_id": video_id,
        "parent_run_id": parent_run_id,
        "config": config,
        "video_file": synthetic_video_file,
    }


def test_tp10_08_append_only_invariant_preserves_detections_and_tracks(
    review_test_env: dict[str, Any],
) -> None:
    """TP10-08: Creating and updating reviews never modifies or deletes detections or tracks."""
    db_path = review_test_env["db_path"]
    parent_run_id = review_test_env["parent_run_id"]
    cfg = review_test_env["config"]

    with database_connection(db_path) as conn:
        initial_detections = [dict(r) for r in fetch_detections_for_tracking(conn, parent_run_id)]
        initial_tracks = [dict(r) for r in fetch_tracks_for_run(conn, parent_run_id)]

    # Create a review with corrections
    review = create_manual_review(
        parent_run_id=parent_run_id,
        frame_number=3,
        timestamp_s=0.3,
        reason="low_confidence_classification",
        detection_id="det_low_conf_1",
        reviewer="senior_analyst",
        corrected_class="auto_rickshaw",
        corrected_bbox={"x1": 58.0, "y1": 58.0, "x2": 122.0, "y2": 142.0},
        status="approved",
        config=cfg,
    )
    assert review["review_status"] == "approved"
    assert review["original_class"] == "motorcycle"
    assert review["corrected_class"] == "auto_rickshaw"

    # Verify that detections and tracks tables are untouched
    with database_connection(db_path) as conn:
        current_detections = [dict(r) for r in fetch_detections_for_tracking(conn, parent_run_id)]
        current_tracks = [dict(r) for r in fetch_tracks_for_run(conn, parent_run_id)]

    assert current_detections == initial_detections
    assert current_tracks == initial_tracks

    # Update review status
    update_manual_review(
        review_id=review["review_id"],
        status="rejected",
        reason="reviewer_reversal",
        config=cfg,
    )

    with database_connection(db_path) as conn:
        after_update_detections = [dict(r) for r in fetch_detections_for_tracking(conn, parent_run_id)]
        after_update_tracks = [dict(r) for r in fetch_tracks_for_run(conn, parent_run_id)]

    assert after_update_detections == initial_detections
    assert after_update_tracks == initial_tracks


def test_tp10_11_snippet_generation_file_output(
    review_test_env: dict[str, Any],
) -> None:
    """TP10-11: Snippet generation creates a playable video file and records path in snippet_path."""
    parent_run_id = review_test_env["parent_run_id"]
    cfg = review_test_env["config"]

    review = create_manual_review(
        parent_run_id=parent_run_id,
        frame_number=3,
        timestamp_s=0.3,
        reason="low_confidence",
        detection_id="det_low_conf_1",
        generate_snippet=True,
        config=cfg,
    )

    assert review["snippet_path"] is not None
    snippet_path = Path(review["snippet_path"])
    assert snippet_path.is_file()
    assert snippet_path.stat().st_size > 0

    # Also test on-demand snippet generation
    review2 = create_manual_review(
        parent_run_id=parent_run_id,
        frame_number=5,
        timestamp_s=0.5,
        reason="bus_occlusion",
        detection_id="det_low_conf_2",
        generate_snippet=False,
        config=cfg,
    )
    assert review2["snippet_path"] is None

    generated_path = generate_snippet_for_review(review2["review_id"], config=cfg)
    assert generated_path.is_file()
    assert generated_path.stat().st_size > 0

    updated2 = get_manual_review_by_id(review2["review_id"], config=cfg)
    assert updated2 is not None
    assert updated2["snippet_path"] == str(generated_path)


def test_tp10_12_database_persistence_and_query_filters(
    review_test_env: dict[str, Any],
) -> None:
    """TP10-12: manual_reviews rows persist with full provenance; queries filter correctly."""
    parent_run_id = review_test_env["parent_run_id"]
    cfg = review_test_env["config"]
    db_path = review_test_env["db_path"]

    r1 = create_manual_review(
        parent_run_id=parent_run_id,
        frame_number=1,
        timestamp_s=0.1,
        reason="uncertain_1",
        status="pending",
        reviewer="alice",
        config=cfg,
    )
    r2 = create_manual_review(
        parent_run_id=parent_run_id,
        frame_number=2,
        timestamp_s=0.2,
        reason="uncertain_2",
        status="approved",
        reviewer="bob",
        corrected_class="car",
        config=cfg,
    )
    r3 = create_manual_review(
        parent_run_id=parent_run_id,
        frame_number=3,
        timestamp_s=0.3,
        reason="uncertain_3",
        status="rejected",
        reviewer="alice",
        config=cfg,
    )

    # Query all
    all_revs = get_manual_reviews(config=cfg)
    assert all_revs["count"] >= 3

    # Filter by reviewer
    alice_revs = get_manual_reviews(reviewer="alice", config=cfg)
    assert alice_revs["count"] == 2
    assert all(r["reviewer"] == "alice" for r in alice_revs["reviews"])

    # Filter by status
    approved_revs = get_manual_reviews(review_status="approved", config=cfg)
    assert approved_revs["count"] == 1
    assert approved_revs["reviews"][0]["review_id"] == r2["review_id"]

    # Filter by limit
    limited = get_manual_reviews(limit=1, config=cfg)
    assert limited["count"] == 1

    # Check stats query
    with database_connection(db_path) as conn:
        stats = fetch_manual_review_stats(conn, parent_run_id)
        assert stats["total_reviews"] >= 3
        assert stats["pending_count"] >= 1
        assert stats["approved_count"] >= 1
        assert stats["rejected_count"] >= 1


def test_tp10_15_cli_commands_end_to_end(
    review_test_env: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """TP10-15: CLI commands execute successfully and output valid JSON."""
    parent_run_id = review_test_env["parent_run_id"]
    cfg = review_test_env["config"]
    cfg_path = tmp_path / "cli_config.yaml"

    import yaml
    cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")

    # 1. find-review-candidates
    monkeypatch.setattr(
        "sys.argv",
        [
            "traffic-vision",
            "find-review-candidates",
            parent_run_id,
            "--confidence-threshold",
            "0.50",
            "--config",
            str(cfg_path),
        ],
    )
    main()
    out = capsys.readouterr().out
    cands_result = json.loads(out)
    assert cands_result["parent_run_id"] == parent_run_id
    assert cands_result["candidate_count"] >= 2

    # 2. create-review
    monkeypatch.setattr(
        "sys.argv",
        [
            "traffic-vision",
            "create-review",
            parent_run_id,
            "--frame",
            "3",
            "--timestamp",
            "0.3",
            "--reason",
            "cli_test_uncertainty",
            "--corrected-class",
            "truck",
            "--corrected-bbox",
            "10,10,100,100",
            "--status",
            "pending",
            "--reviewer",
            "cli_user",
            "--config",
            str(cfg_path),
        ],
    )
    main()
    out = capsys.readouterr().out
    created_result = json.loads(out)
    review_id = created_result["review_id"]
    assert created_result["review_status"] == "pending"
    assert created_result["corrected_class"] == "truck"
    assert json.loads(created_result["corrected_bbox_json"]) == {"x1": 10.0, "y1": 10.0, "x2": 100.0, "y2": 100.0}

    # 3. show-reviews
    monkeypatch.setattr(
        "sys.argv",
        [
            "traffic-vision",
            "show-reviews",
            "--reviewer",
            "cli_user",
            "--config",
            str(cfg_path),
        ],
    )
    main()
    out = capsys.readouterr().out
    show_result = json.loads(out)
    assert show_result["count"] >= 1
    assert any(r["review_id"] == review_id for r in show_result["reviews"])

    # 4. update-review
    monkeypatch.setattr(
        "sys.argv",
        [
            "traffic-vision",
            "update-review",
            review_id,
            "--status",
            "approved",
            "--reviewer",
            "lead_supervisor",
            "--config",
            str(cfg_path),
        ],
    )
    main()
    out = capsys.readouterr().out
    updated_result = json.loads(out)
    assert updated_result["review_status"] == "approved"
    assert updated_result["reviewer"] == "lead_supervisor"

    # 5. generate-review-snippet
    monkeypatch.setattr(
        "sys.argv",
        [
            "traffic-vision",
            "generate-review-snippet",
            review_id,
            "--config",
            str(cfg_path),
        ],
    )
    main()
    out = capsys.readouterr().out
    snippet_result = json.loads(out)
    assert snippet_result["review_id"] == review_id
    assert Path(snippet_result["snippet_path"]).is_file()


def test_candidate_search_rejects_missing_or_incomplete_parent_run(
    review_test_env: dict[str, Any],
) -> None:
    """Parent run existence and completion validation."""
    cfg = review_test_env["config"]
    with pytest.raises(ValueError, match="does not exist"):
        find_review_candidates("non_existent_run_id", config=cfg)
