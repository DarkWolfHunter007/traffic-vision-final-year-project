"""Phase 12 service integration tests: TP12-01, TP12-02, TP12-07..11, TP12-13..14.

All fixtures in this module are synthetic software test fixtures; no real research data or CCTV measurements are fabricated.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

import pytest

from backend.cli import build_parser, main
from backend.config import load_config
from backend.database.connection import bootstrap_database, database_connection
from backend.database.repository import (
    fetch_model_version,
    fetch_production_model,
    insert_crossing_events,
    insert_ground_truth_counts,
    insert_ground_truth_set,
    insert_run,
    insert_video,
    insert_video_segments,
)
from backend.evaluation import (
    EvaluationBox,
    EvaluationError,
    EvaluationLeakageError,
)
from backend.media import sha256_file
from backend.services.evaluation import (
    compare_models,
    evaluate_counting,
    evaluate_detection,
    evaluate_tracking,
    get_model_details,
    list_models,
    register_model,
    select_production_model,
)
from backend.services.ingestion import _utc_now


@pytest.fixture
def synthetic_weights_file(tmp_path: Path) -> Path:
    """Create a synthetic model weights file as a software test fixture."""
    weights = tmp_path / "synthetic_yolo_v1.pt"
    weights.write_bytes(b"SYNTHETIC_MODEL_WEIGHTS_FIXTURE_BYTES_V1")
    return weights


@pytest.fixture
def synthetic_weights_file_v2(tmp_path: Path) -> Path:
    """Create a secondary synthetic model weights file as a software test fixture."""
    weights = tmp_path / "synthetic_yolo_v2.pt"
    weights.write_bytes(b"SYNTHETIC_MODEL_WEIGHTS_FIXTURE_BYTES_V2")
    return weights


@pytest.fixture
def evaluation_test_env(
    tmp_path: Path, synthetic_weights_file: Path, synthetic_weights_file_v2: Path
) -> dict[str, Any]:
    """Set up database and synthetic dataset environment for evaluation testing."""
    db_path = tmp_path / "evaluation_test.sqlite3"
    bootstrap_database(db_path)

    config = load_config()
    config["paths"]["database_path"] = str(db_path)
    config["evaluation"]["output_dir"] = str(tmp_path / "evaluations")

    video_id = "vid_synthetic_eval_fixture"
    video_sha = "sha256_synthetic_eval_video"
    run_id = str(uuid4())
    now = _utc_now()

    with database_connection(db_path) as conn:
        insert_video(
            conn,
            {
                "video_id": video_id,
                "filename": "synthetic_eval_video.mp4",
                "path": str(tmp_path / "synthetic_eval_video.mp4"),
                "sha256": video_sha,
                "fps_nominal": 10.0,
                "width": 640,
                "height": 480,
                "duration_s": 10.0,
                "frame_count": 100,
                "variable_frame_rate": 0,
                "wall_clock_start": None,
                "ingested_at": now,
                "metadata_json": "{}",
            },
        )

    # Synthetic dataset manifest fixture with train and val splits
    synthetic_manifest = {
        "dataset_version": "ds_fixture_v1",
        "created_at": now,
        "class_mapping": {"car": 0, "bus": 1},
        "samples": [
            {
                "sample_id": "s_train_1",
                "video_id": video_id,
                "frame_number": 10,
                "split": "train",
                "annotations": [{"class_id": 0, "x_center": 0.2, "y_center": 0.2, "width": 0.2, "height": 0.2}],
            },
            {
                "sample_id": "s_val_1",
                "video_id": video_id,
                "frame_number": 20,
                "split": "val",
                "annotations": [
                    {"class_id": 0, "x_center": 0.3, "y_center": 0.3, "width": 0.2, "height": 0.2},
                    {"class_id": 1, "x_center": 0.7, "y_center": 0.7, "width": 0.3, "height": 0.3},
                ],
            },
        ],
    }

    manifest_path = tmp_path / "dataset" / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(synthetic_manifest), encoding="utf-8")

    return {
        "db_path": db_path,
        "config": config,
        "video_id": video_id,
        "weights_path": synthetic_weights_file,
        "weights_path_v2": synthetic_weights_file_v2,
        "manifest_path": manifest_path,
        "manifest_data": synthetic_manifest,
        "tmp_path": tmp_path,
    }


def test_tp12_01_model_registration(evaluation_test_env: dict[str, Any]) -> None:
    env = evaluation_test_env
    res = register_model(
        model_version="candidate_yolo_v1",
        model_path=env["weights_path"],
        dataset_version="ds_fixture_v1",
        config=env["config"],
    )

    assert res["model_version"] == "candidate_yolo_v1"
    assert res["sha256"] == sha256_file(env["weights_path"])
    assert res["dataset_version"] == "ds_fixture_v1"
    assert res["selected_for_production"] == 0

    # Duplicate registration must fail
    with pytest.raises(EvaluationError, match="already registered"):
        register_model(
            model_version="candidate_yolo_v1",
            model_path=env["weights_path"],
            config=env["config"],
        )

    # Missing model path must fail
    with pytest.raises(EvaluationError, match="does not exist"):
        register_model(
            model_version="candidate_nonexistent",
            model_path=env["tmp_path"] / "nonexistent.pt",
            config=env["config"],
        )


def test_tp12_02_detection_evaluation_refuses_training_leakage(evaluation_test_env: dict[str, Any]) -> None:
    env = evaluation_test_env
    register_model("candidate_yolo_v1", env["weights_path"], config=env["config"])

    # Attempting to evaluate on 'train' split MUST raise EvaluationLeakageError
    manifest_tampered = {
        "dataset_version": "ds_fixture_v1",
        "class_mapping": {"car": 0},
        "samples": [
            {
                "sample_id": "s_train_1",
                "video_id": env["video_id"],
                "frame_number": 10,
                "split": "train",
                "annotations": [{"class_id": 0, "x_center": 0.2, "y_center": 0.2, "width": 0.2, "height": 0.2}],
            }
        ],
    }

    with pytest.raises(EvaluationLeakageError, match="Data leakage detected: sample 's_train_1'"):
        evaluate_detection(
            model_version="candidate_yolo_v1",
            dataset_path=manifest_tampered,
            split="train",
            config=env["config"],
        )


def test_tp12_03_and_07_detection_evaluation_provenance_and_metrics(evaluation_test_env: dict[str, Any]) -> None:
    env = evaluation_test_env
    register_model("candidate_yolo_v1", env["weights_path"], config=env["config"])

    # Synthetic prediction for s_val_1: 1 perfect car TP, 1 perfect bus TP
    preds = [
        [
            EvaluationBox("car", 0.2, 0.2, 0.4, 0.4, confidence=0.92),
            EvaluationBox("bus", 0.55, 0.55, 0.85, 0.85, confidence=0.88),
        ]
    ]

    report = evaluate_detection(
        model_version="candidate_yolo_v1",
        dataset_path=env["manifest_path"],
        split="val",
        precomputed_predictions=preds,
        config=env["config"],
    )

    # Invariants
    assert report["model_version"] == "candidate_yolo_v1"
    assert report["split_evaluated"] == "val"
    assert report["dataset_manifest_hash"] == sha256_file(env["manifest_path"])
    assert "config_hash" in report
    assert report["macro_precision"] == 1.0
    assert report["macro_recall"] == 1.0
    assert report["map50"] == 1.0

    # Check persistence in database
    with database_connection(env["db_path"]) as conn:
        m_row = fetch_model_version(conn, "candidate_yolo_v1")
        assert m_row is not None
        metrics_json = json.loads(m_row["metrics_json"])
        assert len(metrics_json["evaluations"]) == 1
        assert metrics_json["latest_detection"]["map50"] == 1.0


def test_tp12_08_and_09_counting_validation_against_phase06_ground_truth(evaluation_test_env: dict[str, Any]) -> None:
    env = evaluation_test_env
    register_model("candidate_yolo_v1", env["weights_path"], config=env["config"])

    run_id = "run_counting_eval_fixture"
    now = _utc_now()

    with database_connection(env["db_path"]) as conn:
        insert_run(
            conn,
            {
                "run_id": run_id,
                "parent_run_id": None,
                "video_id": env["video_id"],
                "model_version": "candidate_yolo_v1",
                "config_hash": "cfg_hash_eval",
                "config_json": "{}",
                "schema_version": "schema_ver_eval",
                "code_version": "code_ver_eval",
                "source_video_sha256": "sha256_synthetic_eval_video",
                "started_at": now,
                "status": "completed",
                "notes": "Synthetic completed counting run",
            },
        )

        # Ground truth set and segments
        gt_set_id = "gt_set_fixture_01"
        insert_ground_truth_set(
            conn,
            {
                "ground_truth_set_id": gt_set_id,
                "name": "Phase 06 Benchmark Set",
                "source_description": "Synthetic software fixture",
                "split_group": "eval_group_1",
                "created_at": now,
            },
        )

        seg_id = "seg_eval_01"
        insert_video_segments(
            conn,
            [
                {
                    "segment_id": seg_id,
                    "video_id": env["video_id"],
                    "start_s": 0.0,
                    "end_s": 10.0,
                    "start_frame": 0,
                    "end_frame": 100,
                    "label": "eval_clip",
                    "condition_notes": "software fixture",
                }
            ],
        )

        # 10 cars observed manually
        insert_ground_truth_counts(
            conn,
            [
                {
                    "ground_truth_count_id": "gtc_01",
                    "ground_truth_set_id": gt_set_id,
                    "video_segment_id": seg_id,
                    "approach": "north",
                    "movement": "through",
                    "vehicle_class": "car",
                    "observed_count": 10,
                }
            ],
        )

        # 9 cars counted by model run (deduplicated = 0) -> 10% error
        line_id = "line_north_01"
        conn.execute(
            """
            INSERT INTO counting_lines (line_id, video_id, name, approach, geometry_json, bidirectional, config_version, geometry_sha256)
            VALUES (?, ?, 'North Line', 'north', '{"endpoints": [[0,0], [10,10]]}', 0, 'v1', 'hash')
            """,
            (line_id, env["video_id"]),
        )

        crossings = [
            {
                "crossing_event_id": f"cross_{i}",
                "run_id": run_id,
                "video_id": env["video_id"],
                "line_id": line_id,
                "track_id": i,
                "frame_number": i * 10,
                "timestamp_s": float(i),
                "vehicle_class": "car",
                "direction": "forward",
                "approach": "north",
                "movement": "through",
                "line_config_version": "v1",
                "deduplicated": 0,
            }
            for i in range(1, 10)
        ]
        insert_crossing_events(conn, crossings)

    # Run counting evaluation
    report = evaluate_counting(
        model_version="candidate_yolo_v1",
        run_id=run_id,
        ground_truth_set_id=gt_set_id,
        config=env["config"],
    )

    assert report["total_counted"] == 9
    assert report["total_observed"] == 10
    assert report["total_absolute_error"] == 1
    assert report["total_percent_error"] == 10.0
    assert report["error_tolerance_pct"] == 10.0
    assert report["tolerance_met"] is True

    # Invariant: Never declare acceptance
    assert report["acceptance_status"] == "pending_independent_review"
    assert report["acceptance_declaration"] is None
    assert report["research_acceptance"] == "external"


def test_tp12_10_tracking_evaluation_id_switches(evaluation_test_env: dict[str, Any]) -> None:
    env = evaluation_test_env
    register_model("candidate_yolo_v1", env["weights_path"], config=env["config"])

    # Synthetic ground truth association sequence with 1 switch:
    # frame 1: gt_id 10 -> track_id 1
    # frame 2: gt_id 10 -> track_id 1
    # frame 3: gt_id 10 -> track_id 2 (ID switch)
    assignments = [
        (1, 10, 1),
        (2, 10, 1),
        (3, 10, 2),
    ]

    report = evaluate_tracking(
        model_version="candidate_yolo_v1",
        run_id="run_track_eval",
        ground_truth_assignments=assignments,
        config=env["config"],
    )
    assert report["id_switches"] == 1

    # When unmeasured, reports None (N/A)
    report_unmeasured = evaluate_tracking(
        model_version="candidate_yolo_v1",
        run_id="run_track_eval",
        ground_truth_assignments=None,
        config=env["config"],
    )
    assert report_unmeasured["id_switches"] is None
    assert report_unmeasured["track_continuity"] is None


def test_tp12_13_production_model_selection_safeguard(evaluation_test_env: dict[str, Any]) -> None:
    env = evaluation_test_env
    register_model("model_alpha", env["weights_path"], config=env["config"])
    register_model("model_beta", env["weights_path_v2"], config=env["config"])

    # Initially, no production model is selected
    with database_connection(env["db_path"]) as conn:
        assert fetch_production_model(conn) is None

    # Explicitly activate model_alpha
    res1 = select_production_model("model_alpha", config=env["config"])
    assert res1["selected_for_production"] == 1

    with database_connection(env["db_path"]) as conn:
        prod = fetch_production_model(conn)
        assert prod is not None
        assert prod["model_version"] == "model_alpha"

    # Explicitly activate model_beta (must atomic swap and unseat model_alpha)
    res2 = select_production_model("model_beta", config=env["config"])
    assert res2["selected_for_production"] == 1

    with database_connection(env["db_path"]) as conn:
        prod = fetch_production_model(conn)
        assert prod is not None
        assert prod["model_version"] == "model_beta"
        alpha = fetch_model_version(conn, "model_alpha")
        assert alpha["selected_for_production"] == 0

    # Non-existent model selection must be rejected
    with pytest.raises(EvaluationError, match="does not exist"):
        select_production_model("model_nonexistent", config=env["config"])


def test_tp12_14_cli_evaluation_commands(evaluation_test_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    env = evaluation_test_env
    cfg_file = env["tmp_path"] / "test_config.yaml"
    import yaml
    cfg_file.write_text(yaml.safe_dump(env["config"]), encoding="utf-8")

    # 1. register-model
    monkeypatch.setattr(
        "sys.argv",
        ["traffic-vision", "register-model", "cli_model_v1", str(env["weights_path"]), "--config", str(cfg_file)],
    )
    main()
    out = capsys.readouterr().out
    res = json.loads(out)
    assert res["model_version"] == "cli_model_v1"

    # 2. show-model
    monkeypatch.setattr(
        "sys.argv",
        ["traffic-vision", "show-model", "cli_model_v1", "--config", str(cfg_file)],
    )
    main()
    out = capsys.readouterr().out
    res = json.loads(out)
    assert res["model_version"] == "cli_model_v1"

    # 3. select-model
    monkeypatch.setattr(
        "sys.argv",
        ["traffic-vision", "select-model", "cli_model_v1", "--config", str(cfg_file)],
    )
    main()
    out = capsys.readouterr().out
    res = json.loads(out)
    assert res["selected_for_production"] == 1
