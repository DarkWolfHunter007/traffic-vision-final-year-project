# Phase 12 Handoff — Model Evaluation, Validation, and Safeguards

## 1. Delivered Interfaces and Modules

### Pure Evaluation Logic (`backend.evaluation`)
- `EvaluationBox`: Immutable dataclass representing a bounding box for detection evaluation: `(class_name, x1, y1, x2, y2, confidence)`. Coordinates are normalized $[0.0, 1.0]$.
- `calculate_box_iou(box1, box2) -> float`: Computes standard Intersection-over-Union (IoU) between bounding boxes.
- `audit_evaluation_leakage(evaluation_sample_identifiers, dataset_manifest) -> None`: Audits that NO sample ID, frame `(video_id, frame_number)`, or split group in the evaluated set appears in the `train` split of the Phase 11 `manifest.json`. Raises `EvaluationLeakageError` upon detection.
- `match_detections_for_image(predictions, ground_truths, iou_threshold=0.5) -> tuple[list[tuple[EvaluationBox, EvaluationBox]], list[EvaluationBox], list[EvaluationBox]]`: Greedy class-aware matching of predictions to ground-truth objects ordered by prediction confidence descending. Returns `(matches, false_positives, false_negatives)`.
- `calculate_precision_recall(tp, fp, fn) -> tuple[float | None, float | None]`: Computes precision and recall; returns `None` (N/A) when the denominator is zero.
- `calculate_average_precision_for_class(predictions_with_eval, total_ground_truths) -> float | None`: Computes 11-point interpolated Average Precision (AP) across recall thresholds $[0.0, 0.1, ..., 1.0]$. Returns `None` (N/A) if `total_ground_truths == 0` (no fabricated metrics).
- `calculate_confusion_matrix(predictions_by_sample, ground_truths_by_sample, class_names, iou_threshold=0.5) -> dict[str, Any]`: Computes complete class-to-class confusion matrix including `'background'` row for False Positives (predictions with no GT) and `'background'` column for False Negatives (GT with no prediction).
- `calculate_detection_metrics(predictions_by_sample, ground_truths_by_sample, class_names, iou_threshold=0.5, map_iou_thresholds=None) -> dict[str, Any]`: Computes class-wise AP@50, AP@50:95, macro mAP@50, macro mAP@50:95, macro precision/recall, class metrics, and confusion matrix.
- `compare_model_metrics(model_a_metrics, model_b_metrics, model_a_version="model_a", model_b_version="model_b") -> dict[str, Any]`: Computes side-by-side metric deltas without mutating models, deleting records, or declaring an automated winner.
- Exceptions: `EvaluationError`, `EvaluationLeakageError`.

### Model Evaluation Service (`backend.services.evaluation`)
- `register_model(model_version, model_path, dataset_version=None, config=None, repository_root=None, connection=None) -> dict[str, Any]`: Registers a candidate model version in `model_versions`, verifies file existence, calculates cryptographic SHA-256 hash, initializes `selected_for_production = 0`, and records creation timestamp.
- `evaluate_detection(model_version, dataset_path, split="val", detector=None, precomputed_predictions=None, config=None, repository_root=None, connection=None) -> dict[str, Any]`: Evaluates candidate YOLO detection on held-out split (`val` or `test`), runs training leakage audit, computes detection metrics and confusion matrix, records `model_version`, `dataset_manifest_hash`, and `config_hash`, updates `model_versions.metrics_json`, and optionally writes a JSON evaluation report to disk.
- `evaluate_counting(model_version, run_id, ground_truth_set_id=None, config=None, repository_root=None, connection=None) -> dict[str, Any]`: Evaluates counting run against Phase 06 ground truth, checks absolute and percentage error against `counting.error_tolerance_pct` (default 10.0%), enforces acceptance disclaimer (`acceptance_status = "pending_independent_review"`, `acceptance_declaration = None`), and updates `model_versions.metrics_json`.
- `evaluate_tracking(model_version, run_id, ground_truth_assignments=None, config=None, repository_root=None, connection=None) -> dict[str, Any]`: Evaluates CLEAR MOT ID switches when ground-truth associations are provided; explicitly records `None` (N/A) when associations are absent.
- `select_production_model(model_version, config=None, repository_root=None, connection=None) -> dict[str, Any]`: Explicitly activates production model via atomic swap of `selected_for_production = 1`, enforcing the partial unique index constraint.
- `get_model_details(model_version, config=None, repository_root=None, connection=None) -> dict[str, Any]`: Fetches complete model metadata and parsed evaluation metrics from `model_versions`.
- `list_models(config=None, repository_root=None, connection=None) -> list[dict[str, Any]]`: Lists all registered model versions and evaluation summaries.
- `compare_models(model_version_a, model_version_b, config=None, repository_root=None, connection=None) -> dict[str, Any]`: Fetches evaluation metrics for two models and generates side-by-side comparison report.

### Repository Operations (`backend.database.repository`)
- `insert_model_version(connection, model)`: Supports `selected_for_production` (defaulting to 0) and records initial model metadata.
- `fetch_model_version(connection, model_version) -> sqlite3.Row | None`: Fetches a single model record by version.
- `fetch_all_model_versions(connection) -> list[sqlite3.Row]`: Lists all model versions ordered by `created_at DESC`.
- `fetch_production_model(connection) -> sqlite3.Row | None`: Queries the currently active production model (`selected_for_production = 1`).
- `update_model_metrics(connection, model_version, metrics_json) -> None`: Updates `metrics_json` for a registered model version.
- `set_production_model_version(connection, model_version) -> None`: Atomically clears previous production model and sets `selected_for_production = 1` for the specified version.

### CLI Commands (`backend.cli`)
- `traffic-vision register-model VERSION PATH [--dataset-version DVER] [--config CONFIG]`: Registers candidate model weights.
- `traffic-vision evaluate-detection MODEL_VERSION DATASET_PATH [--split SPLIT] [--config CONFIG]`: Evaluates detection performance on held-out split with leakage check.
- `traffic-vision evaluate-counting MODEL_VERSION RUN_ID [--ground-truth-set SET_ID] [--config CONFIG]`: Evaluates counting run against ground truth and tolerance.
- `traffic-vision compare-models MODEL_A MODEL_B [--config CONFIG]`: Compares two evaluated models side-by-side.
- `traffic-vision select-model MODEL_VERSION [--config CONFIG]`: Explicitly activates production model.
- `traffic-vision show-model MODEL_VERSION [--config CONFIG]`: Inspects model metadata and evaluation history.

### FastAPI Application Endpoints (`backend.app`)
- `POST /models/register`: Registers candidate model (`201 Created`).
- `GET /models`: Lists all model versions (`200 OK`).
- `GET /models/{model_version}`: Retrieves model details and evaluations (`200 OK` or `404 Not Found`).
- `POST /models/evaluate-detection`: Evaluates detection with leakage audit (`200 OK` or `422 Unprocessable Content`).
- `POST /models/evaluate-counting`: Evaluates counting against Phase 06 ground truth (`200 OK`).
- `POST /models/compare`: Returns side-by-side metric comparison (`200 OK`).
- `POST /models/select-production`: Explicitly activates production model (`200 OK`).
- Typed request models: `RegisterModelRequest`, `EvaluateDetectionRequest`, `EvaluateCountingRequest`, `CompareModelsRequest`, `SelectProductionModelRequest`.

---

## 2. Changed and Created Files

| File | Status | Description |
|---|---|---|
| `prompts/phase_12_model_evaluation.md` | Authority | Revised in place to eliminate ambiguities: exact tables/columns, config keys with defaults, CLI/API interfaces, and measurable test plan TP12-01..TP12-16. |
| `configs/default.yaml` | Modified | Added default `evaluation` configuration section (`iou_threshold`, `map_iou_thresholds`, `confidence_threshold`, `held_out_split`, `counting_tolerance_pct`, `output_dir`). |
| `backend/config.py` | Modified | Added `evaluation` section defaults to `DEFAULT_CONFIG` and validation rules in `_validate()`. |
| `backend/database/repository.py` | Modified | Added additive queries: `fetch_model_version`, `fetch_all_model_versions`, `fetch_production_model`, `update_model_metrics`, `set_production_model_version`, and updated `insert_model_version`. |
| `backend/evaluation.py` | Created | Pure evaluation logic: `EvaluationBox`, IoU computation, detection matching, precision/recall, AP/mAP@50/mAP@50:95, confusion matrix, leakage audit, and model comparison. |
| `backend/services/evaluation.py` | Created | Model evaluation service: model registration, detection evaluation, counting validation, tracking evaluation, side-by-side comparison, and active production model safeguards. |
| `backend/cli.py` | Modified | Added additive CLI subcommands: `register-model`, `evaluate-detection`, `evaluate-counting`, `compare-models`, `select-model`, `show-model`. |
| `backend/app.py` | Modified | Added additive FastAPI routes and typed Pydantic models for model registration, detection evaluation, counting validation, comparison, and production model selection. |
| `tests/test_evaluation.py` | Created | Pure logic unit tests covering TP12-02, TP12-03, TP12-04, TP12-05, TP12-06, TP12-12, TP12-16. |
| `tests/test_evaluation_service.py` | Created | Integration tests covering TP12-01 (registration), TP12-02 (leakage rejection), TP12-03/07 (detection metrics & provenance), TP12-08/09 (counting validation & tolerance), TP12-10 (tracking ID switches), TP12-13 (active-model safeguard), TP12-14 (CLI commands). |
| `tests/test_evaluation_api.py` | Created | Integration tests covering TP12-15 (FastAPI model registration, listing, evaluation, comparison, and production selection). |
| `docs/handoffs/phase_12/HANDOFF.md` | Created | This handoff document. |

---

## 3. Schema Usage and Invariants

**No database schema change was required.** All necessary tables and partial indexes already existed in `backend/database/schema.sql`:
- **`model_versions`**:
  - `model_version`: Text primary key.
  - `model_path`: Filesystem path to weights file.
  - `sha256`: Cryptographic hash of model weights.
  - `dataset_version`: Optional reference to Phase 11 dataset version.
  - `created_at`: UTC ISO timestamp.
  - `selected_for_production`: Integer flag (0 or 1).
  - `metrics_json`: Canonical JSON string storing evaluation records, detection metrics, counting comparisons, tracking stats.
- Partial unique index `idx_one_production_model`: Enforces that at most one model can have `selected_for_production = 1` at any time.

### Invariants Enforced
1. **Evaluation Only (No Training Loops)**: This phase does not execute YOLO training loops; candidate models are versioned, fingerprinted via SHA-256, evaluated against held-out data, and compared.
2. **Held-Out Data Only**: Detection evaluations are strictly computed from held-out splits (`val` or `test`).
3. **Training Data Leakage Audit**: `audit_evaluation_leakage` strictly audits that no evaluated sample or frame tuple is present in the `train` split of `manifest.json`. Leakage attempts raise `EvaluationLeakageError`.
4. **Cryptographic Provenance**: Every evaluation record preserves `model_version`, `dataset_manifest_hash` (SHA-256 of `manifest.json`), and `config_hash`.
5. **No Fabricated Metrics**: Missing data or classes with 0 ground-truth instances report `None` (N/A) rather than 0.0 or synthetic scores. Unmeasured tracking or speed metrics report `None` (N/A).
6. **Counting Tolerance Without Acceptance**: Compares counted vehicles against Phase 06 ground truth and tolerance (`counting.error_tolerance_pct`), records factual error, but explicitly sets `acceptance_status = "pending_independent_review"` and `acceptance_declaration = None`. Independent civil engineering review makes the acceptance determination.
7. **Active-Model Safeguard**: Active model can only be changed via explicit selection; silent replacement is blocked, and uniqueness is enforced atomically.
8. **No Fabricated Research Data**: All test fixtures are synthetic software fixtures, explicitly labelled as such.

---

## 4. Configuration Schema and Defaults

In `configs/default.yaml`:
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

Validated in `backend/config.py`:
- `iou_threshold`: Float $\in [0.0, 1.0]$ (default 0.5).
- `map_iou_thresholds`: Non-empty list of floats $\in [0.0, 1.0]$ in ascending order.
- `confidence_threshold`: Float $\in [0.0, 1.0]$ (default 0.25).
- `held_out_split`: String, must be `'val'` or `'test'` (default `'val'`).
- `counting_tolerance_pct`: Positive float $> 0.0$ (default 10.0).
- `output_dir`: Non-empty string path (default `'data/processed/evaluations'`).

---

## 5. Raw Test Results

### Full Pytest Suite (`uv run pytest -q`)
```text
........................................................................ [ 33%]
........................................................................ [ 67%]
......................................................................   [100%]
214 passed in 31.74s
```

### Focused Phase 12 Tests (`uv run pytest tests/test_evaluation.py tests/test_evaluation_service.py tests/test_evaluation_api.py -v`)
```text
============================= test session starts =============================
platform win32 -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0 -- D:\Work\Personal\traffic-vision-final-year-project\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: D:\Work\Personal\traffic-vision-final-year-project
configfile: pyproject.toml
plugins: anyio-4.15.1
collecting ... collected 18 items

tests/test_evaluation.py::test_tp12_box_iou_calculation PASSED           [  5%]
tests/test_evaluation.py::test_tp12_02_leakage_audit_rejects_training_samples PASSED [ 11%]
tests/test_evaluation.py::test_tp12_03_detection_metrics_precision_recall_ap50 PASSED [ 16%]
tests/test_evaluation.py::test_tp12_04_map50_95_multi_threshold_evaluation PASSED [ 22%]
tests/test_evaluation.py::test_tp12_05_confusion_matrix_computation PASSED [ 27%]
tests/test_evaluation.py::test_tp12_06_missing_data_reports_none_not_fabricated PASSED [ 33%]
tests/test_evaluation.py::test_tp12_12_side_by_side_model_comparison PASSED [ 38%]
tests/test_evaluation.py::test_tp12_16_configuration_validation PASSED   [ 44%]
tests/test_evaluation_service.py::test_tp12_01_model_registration PASSED [ 50%]
tests/test_evaluation_service.py::test_tp12_02_detection_evaluation_refuses_training_leakage PASSED [ 55%]
tests/test_evaluation_service.py::test_tp12_03_and_07_detection_evaluation_provenance_and_metrics PASSED [ 61%]
tests/test_evaluation_service.py::test_tp12_08_and_09_counting_validation_against_phase06_ground_truth PASSED [ 66%]
tests/test_evaluation_service.py::test_tp12_10_tracking_evaluation_id_switches PASSED [ 72%]
tests/test_evaluation_service.py::test_tp12_13_production_model_selection_safeguard PASSED [ 77%]
tests/test_evaluation_service.py::test_tp12_14_cli_evaluation_commands PASSED [ 83%]
tests/test_evaluation_api.py::test_tp12_15_register_and_list_models_api PASSED [ 88%]
tests/test_evaluation_api.py::test_tp12_15_evaluate_detection_and_leakage_api PASSED [ 94%]
tests/test_evaluation_api.py::test_tp12_15_compare_and_select_production_api PASSED [100%]

============================= 18 passed in 3.94s ==============================
```

---

## 6. Assumptions and Limitations

1. **Evaluation Only**: In accordance with the prompt specification, this phase implements evaluation, validation, version inventory, and safeguards. Retraining loops and active model weight fine-tuning are managed externally.
2. **Offline Active Evaluation**: Evaluation consumes exported dataset artifacts (`manifest.json`, `dataset.yaml`) from Phase 11.
3. **Acceptance Responsibility**: Counter validation reports percentage error and compares against `counting.error_tolerance_pct`, but never declares that the system is accepted. Civil engineering validation remains external.
4. **Tracking Quality Proxies**: When ground-truth track identities are available for benchmark clips, CLEAR MOT ID switches are computed using `evaluate_id_switches`. When associations are absent, tracking ID switches and continuity are preserved as `None` (N/A) without fabrication.

---

## 7. Next-Phase Dependencies (Phase 13: Exports, Research Summaries, and Dashboard)

1. Phase 13 consumes model evaluations stored in `model_versions.metrics_json` for reporting model performance summaries in exports and dashboards.
2. Phase 13 can query the active production model via `fetch_production_model` to annotate exports with the production model version and SHA-256 fingerprint.

---

## 8. Independent Review Notice

> Do not perform the final checks or acceptance review in this task. Prompt checking, implementation review, testing review, and completion verification will be performed separately by Pro subagents that are different from the normal implementation model.
> Run your own phase tests and report raw output, but do not declare the phase accepted.
