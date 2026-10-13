# Phase 12 - Model Evaluation and Validation

## Objective
Implement only candidate model versioning, detection evaluation, tracking evaluation, counting validation, and production model selection safeguards (evaluation only; no training loops). This prompt is independently executable after the stated dependencies are complete.

## Master sections implemented
Model Improvement, Validation, Tracking, Counting, Configuration, Provenance, Data Integrity, Out of scope, Phase gates (Sections 4, 5, 8, 12, 17, 18, 19, 20, 21, 22).

## Boundary
Implement nothing except this phase. Do not silently implement training code or other-phase functionality (e.g. Phase 13 export/dashboard).
Evaluation only (no training): candidate model weights are registered, evaluated against held-out data only, and compared.
Use `backend/database/schema.sql` and `docs/data_dictionary.md` as the canonical data contract.
Every derived/result row must retain `run_id` and relevant source video/frame/timestamp provenance.
Never fabricate research data (no invented calibration points, ground truth, or measurements; use clearly-labelled software fixtures in tests only).
No fabricated metrics: report `None` / `N/A` when evaluation or reference data is missing.

## Scope
- Candidate model versioning and inventory:
  - Register candidate model versions in `model_versions` (`model_version`, `model_path`, `sha256`, `dataset_version`, `created_at`, `selected_for_production`, `metrics_json`).
  - Calculate weights file SHA-256 for cryptographic integrity and verification.
  - Query and list model versions and inspect historical evaluation metrics.
- Detection evaluation on held-out data only:
  - Evaluate candidate YOLO models against held-out dataset splits (`val` or `test`) from Phase 11 datasets (`manifest.json` / `dataset.yaml`).
  - Leakage check: refuse to evaluate on data present in a training manifest! Inspect the dataset manifest and strictly verify that no evaluated sample or split group belongs to the `train` split. Raise `EvaluationLeakageError` if leakage is detected.
  - Compute detection metrics: class-wise and macro Precision, Recall, Average Precision (AP@50), and Mean Average Precision (mAP@50 and mAP@50:95 across IoU thresholds 0.50 to 0.95 in steps of 0.05).
  - Compute class-level confusion matrix matching predictions to ground-truth objects using IoU threshold (default 0.5), including True Positives, False Positives (predictions without GT), and False Negatives (GT without prediction / background) for each configured vehicle class.
  - Record complete provenance on every evaluation: `model_version`, `dataset_manifest_hash` (SHA-256 of `manifest.json`), and `config_hash`.
  - Missing data policy: when a class has no ground-truth instances in the evaluated split, report AP as `None` / `"N/A"`, never fabricate 0.0 or synthetic scores.
- Counting error validation against Phase 06 ground truth:
  - Evaluate model run vehicle counts against Phase 06 ground truth (`ground_truth_sets`, `video_segments`, `ground_truth_counts`).
  - Compute absolute error (`abs(counted - observed)`), percentage error (`abs(counted - observed) / observed * 100` where observed > 0), and mean absolute error.
  - Compare measured percentage error against configured Phase 06 counting tolerance (`counting.error_tolerance_pct`, default 10.0%).
  - Acceptance invariant: NEVER declare counter acceptance. The evaluation report records the tolerance and whether the error was within tolerance as a factual metric, but explicitly states `acceptance_status = "pending_independent_review"`. Independent review makes the final acceptance decision.
- Tracking evaluation:
  - Evaluate CLEAR MOT identity switches using `backend.tracking.evaluate_id_switches` when ground-truth vehicle trajectory identities exist for documented clips.
  - When tracking ground-truth associations are unavailable, report ID switches and continuity as `None` / `"N/A"`, never fabricate.
- Speed/queue reference evaluation:
  - Evaluate speed and queue MAE/RMSE only when manual reference observations exist; otherwise report `None` / `"N/A"`.
- Side-by-side model comparison:
  - Compare evaluation metrics across candidate models without overwriting or deleting prior model records or metrics.
- Active-model production selection safeguard:
  - Safe, explicit promotion to production (`selected_for_production = 1`).
  - Prevent silent replacement: the production model can only be changed via explicit selection command/API.
  - Maintain canonical schema invariant: at most one model in `model_versions` has `selected_for_production = 1`.
- Interfaces:
  - CLI subcommands in `backend/cli.py`: `register-model`, `evaluate-detection`, `evaluate-counting`, `compare-models`, `select-model`, `show-model`.
  - FastAPI application endpoints in `backend/app.py`: `POST /models/register`, `GET /models`, `GET /models/{model_version}`, `POST /models/evaluate-detection`, `POST /models/evaluate-counting`, `POST /models/compare`, `POST /models/select-production`.

## Inputs and dependencies
- Phase 01: canonical database connection, schema bootstrap, `processing_runs`, `videos`, config loading, provenance hashing (`backend.config`).
- Phase 02: detection primitives (`UltralyticsDetector`, `Detection`, `RawDetection`, bounding boxes, `backend.detection`).
- Phase 03: tracking primitives (`backend.tracking.evaluate_id_switches`).
- Phase 06: counting ground truth (`ground_truth_sets`, `video_segments`, `ground_truth_counts`), counting comparison logic (`backend.counting.calculate_counting_comparison`), counting tolerance (`counting.error_tolerance_pct`).
- Phase 11: active-learning dataset artifacts (`manifest.json`, `dataset.yaml`, split definitions).

## Database schema and persistence
Prefer no schema change: canonical tables already exist in `backend/database/schema.sql`:
- **`model_versions`**:
  - `model_version`: TEXT PRIMARY KEY
  - `model_path`: TEXT NOT NULL
  - `sha256`: TEXT NOT NULL
  - `dataset_version`: TEXT (nullable)
  - `created_at`: TEXT NOT NULL
  - `selected_for_production`: INTEGER NOT NULL DEFAULT 0 CHECK (selected_for_production IN (0, 1))
  - `metrics_json`: TEXT (JSON string storing evaluation records, detection metrics, counting errors, tracking stats)
- Partial unique index `idx_one_production_model` on `model_versions(selected_for_production)` WHERE `selected_for_production = 1` enforces at most one production model at the database level.
- Evaluation reports are stored in `model_versions.metrics_json` and written as JSON artifacts under `data/processed/evaluations/`.

## Configuration
Add an `evaluation` section to `configs/default.yaml` and validate it in `backend/config.py`:
```yaml
evaluation:
  iou_threshold: 0.5
  map_iou_thresholds:
    - 0.5
    - 0.55
    - 0.6
    - 0.65
    - 0.7
    - 0.75
    - 0.8
    - 0.85
    - 0.9
    - 0.95
  confidence_threshold: 0.25
  held_out_split: val
  counting_tolerance_pct: 10.0
  output_dir: data/processed/evaluations
```
Validation rules:
- `iou_threshold`: float between 0.0 and 1.0 (default 0.5).
- `map_iou_thresholds`: non-empty list of floats strictly between 0.0 and 1.0 in ascending order.
- `confidence_threshold`: float between 0.0 and 1.0 (default 0.25).
- `held_out_split`: string, must be `'val'` or `'test'` (default `'val'`).
- `counting_tolerance_pct`: positive float > 0.0 (default 10.0).
- `output_dir`: non-empty string directory path.

## Data and metadata
Use canonical field names from `backend/database/schema.sql` and `docs/data_dictionary.md`.
Preserve `model_version`, `dataset_version`, `dataset_manifest_hash`, `config_hash`, `code_version`, `created_at`, `run_id`, and `video_id`.
Never fabricate research data or evaluation metrics. Missing ground truth or predictions must produce `None` / `"N/A"`.

## Interface contract
- Pure logic module in `backend/evaluation.py`:
  - `calculate_iou(box1, box2) -> float`: Computes intersection over union between two bounding boxes.
  - `match_detections_to_ground_truth(predictions, ground_truths, iou_threshold=0.5) -> tuple[list[tuple[Any, Any]], list[Any], list[Any]]`: Matches predictions to ground truth objects per class using greedy confidence ranking.
  - `calculate_precision_recall(matches, false_positives, false_negatives) -> dict[str, float | None]`: Computes precision and recall; returns `None` when denominator is 0.
  - `calculate_average_precision(recalls, precisions) -> float | None`: Computes 11-point or all-point interpolated AP under PR curve.
  - `calculate_detection_metrics(predictions_by_sample, ground_truths_by_sample, class_mapping, iou_threshold=0.5, map_iou_thresholds=None) -> dict[str, Any]`: Computes class-wise AP, macro mAP@50, mAP@50:95, and macro precision/recall.
  - `calculate_confusion_matrix(predictions_by_sample, ground_truths_by_sample, class_names, iou_threshold=0.5) -> dict[str, Any]`: Computes class-to-class confusion matrix including background false positives and false negatives.
  - `audit_evaluation_leakage(evaluation_sample_ids, dataset_manifest) -> None`: Raises `EvaluationLeakageError` if any evaluation sample belongs to the dataset's training split.
  - `compare_model_metrics(model_a_metrics, model_b_metrics) -> dict[str, Any]`: Computes side-by-side metric diff without mutating models or declaring an automated winner.
- Service module in `backend/services/evaluation.py`:
  - `register_model(model_version, model_path, dataset_version=None, config=None, repository_root=None, connection=None) -> dict[str, Any]`
  - `evaluate_detection(model_version, dataset_path, split="val", detector=None, config=None, repository_root=None, connection=None) -> dict[str, Any]`
  - `evaluate_counting(model_version, run_id, ground_truth_set_id=None, config=None, repository_root=None, connection=None) -> dict[str, Any]`
  - `evaluate_tracking(model_version, run_id, ground_truth_assignments=None, config=None, repository_root=None, connection=None) -> dict[str, Any]`
  - `select_production_model(model_version, config=None, repository_root=None, connection=None) -> dict[str, Any]`
  - `get_model_details(model_version, config=None, repository_root=None, connection=None) -> dict[str, Any]`
  - `list_models(config=None, repository_root=None, connection=None) -> list[dict[str, Any]]`
  - `compare_models(model_version_a, model_version_b, config=None, repository_root=None, connection=None) -> dict[str, Any]`
- Repository operations in `backend/database/repository.py`:
  - `fetch_model_version(connection, model_version) -> sqlite3.Row | None`
  - `fetch_all_model_versions(connection) -> list[sqlite3.Row]`
  - `fetch_production_model(connection) -> sqlite3.Row | None`
  - `update_model_metrics(connection, model_version, metrics_json) -> None`
  - `set_production_model_version(connection, model_version) -> None`
- CLI commands in `backend/cli.py`:
  - `traffic-vision register-model VERSION PATH [--dataset-version DVER] [--config CONFIG]`
  - `traffic-vision evaluate-detection MODEL_VERSION DATASET_PATH [--split SPLIT] [--config CONFIG]`
  - `traffic-vision evaluate-counting MODEL_VERSION RUN_ID [--ground-truth-set SET_ID] [--config CONFIG]`
  - `traffic-vision compare-models MODEL_A MODEL_B [--config CONFIG]`
  - `traffic-vision select-model MODEL_VERSION [--config CONFIG]`
  - `traffic-vision show-model MODEL_VERSION [--config CONFIG]`
- FastAPI endpoints in `backend/app.py`:
  - `POST /models/register`: Register candidate model version.
  - `GET /models`: List all model versions.
  - `GET /models/{model_version}`: Retrieve model details and evaluation metrics.
  - `POST /models/evaluate-detection`: Run held-out detection evaluation with leakage check.
  - `POST /models/evaluate-counting`: Run counting evaluation against Phase 06 ground truth.
  - `POST /models/compare`: Return side-by-side model comparison.
  - `POST /models/select-production`: Explicitly select production model.

## Error handling
- Reject or raise `EvaluationLeakageError` if any evaluated sample or group appears in the training split of the dataset manifest.
- Reject model registration if model weights file does not exist or version string is empty.
- Reject evaluation if model version is not registered in `model_versions`.
- Reject counting evaluation if the evaluated run was not executed with the specified model version.
- Preserve missing measurements as `None` / `"N/A"` without inventing numbers or substituting zero.
- Disallow implicit or silent replacement of the active production model.

## Tests and evidence
Add focused tests:
- `tests/test_evaluation.py`: Pure logic unit tests (IoU, precision/recall, AP, mAP@50, mAP@50:95, confusion matrix, leakage rejection, missing-data handling, provenance tracking).
- `tests/test_evaluation_service.py`: Service orchestration, model registration, detection evaluation on held-out split, counting validation against Phase 06 ground truth, tracking evaluation, side-by-side comparison, active-model safeguard, and CLI commands.
- `tests/test_evaluation_api.py`: FastAPI endpoints for model registration, evaluation, comparison, and production model selection.
All existing tests and new phase tests must pass (`uv run pytest -q`).
Report raw pytest output in `docs/handoffs/phase_12/HANDOFF.md`.
Test fixtures must be clearly labelled software fixtures; never fabricate research data.

## Handoff
Create `docs/handoffs/phase_12/HANDOFF.md` containing changed files, interfaces, schema changes, config keys/defaults, input/output contracts, raw test results, assumptions, limitations, unresolved issues, and dependencies for Phase 13.

## Completion criteria (measurable test plan TP12-01..TP12-16)
- **TP12-01**: Model version registration: records `model_version`, `model_path`, sha256 hash, `dataset_version`, and `created_at` in `model_versions`.
- **TP12-02**: Training data leakage rejection: evaluation on samples present in training manifest is strictly blocked with `EvaluationLeakageError`.
- **TP12-03**: Detection metrics accuracy: precision, recall, AP@50, and mAP@50 correctly computed for known test bounding boxes.
- **TP12-04**: Multi-threshold mAP@50:95: computed across IoU thresholds 0.50 to 0.95 in 0.05 steps.
- **TP12-05**: Confusion matrix computation: per-class True Positives, False Positives (predictions without GT), and False Negatives (GT without prediction) correctly tabulated.
- **TP12-06**: Missing data reporting: classes with 0 instances report `None` / `N/A`, never fabricated 0.0 or synthetic scores.
- **TP12-07**: Provenance tracking: every evaluation records `model_version`, `dataset_manifest_hash`, and `config_hash`.
- **TP12-08**: Counting validation against Phase 06 ground truth: absolute and percentage error calculation per approach/movement/class.
- **TP12-09**: Counting tolerance comparison without declaring acceptance: compares against Phase 06 tolerance, records `acceptance_status: "pending_independent_review"`, and disclaims acceptance declaration.
- **TP12-10**: Tracking evaluation: MOT ID switches calculated when ground-truth associations exist; reported as unmeasured/N/A when absent.
- **TP12-11**: Speed/queue reference evaluation: MAE/RMSE calculated only when reference data exists; otherwise reported as unmeasured/N/A.
- **TP12-12**: Side-by-side model comparison: compares metrics between candidate models without mutating or deleting previous versions.
- **TP12-13**: Active-model production selection safeguard: atomic update of `selected_for_production = 1` and prevention of silent replacement.
- **TP12-14**: CLI evaluation commands: `register-model`, `evaluate-detection`, `evaluate-counting`, `compare-models`, `select-model`, and `show-model` execute and output valid JSON.
- **TP12-15**: FastAPI evaluation endpoints: all models and evaluation endpoints return valid responses and correct HTTP status codes.
- **TP12-16**: Configuration validation: `backend/config.py` validates all `evaluation` keys, thresholds, split options, and types.

## Explicit exclusions
Candidate model training loops (evaluation only), automated research acceptance declarations, emissions, congestion index, redesign, MCE, SUMO, silent active-model replacement.

## Independent review
Do not perform the final checks or acceptance review in this task. Prompt checking, implementation review, testing review, and completion verification will be performed separately by Pro subagents that are different from the normal implementation model.
Run your own phase tests and report raw output, but do not declare the phase accepted.