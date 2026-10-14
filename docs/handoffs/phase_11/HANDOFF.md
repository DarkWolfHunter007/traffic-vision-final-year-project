# Phase 11 Handoff — Active-Learning Dataset Preparation and Leakage-Safe Splits

## 1. Delivered Interfaces and Modules

### Pure Dataset Logic (`backend.dataset`)
- `YoloAnnotation`: Immutable dataclass representing normalized YOLO bounding box coordinates `(class_id, x_center, y_center, width, height)` in $[0.0, 1.0]$. Includes `.to_yolo_line()`, `.to_dict()`, and `.from_pixel_box(box, frame_width, frame_height, class_id)`.
- `DatasetSample`: Immutable dataclass representing an exported frame sample with complete provenance matching `(sample_id, video_id, source_video_sha256, run_id, frame_number, timestamp_s, split, split_group, annotations, review_ids, reviewers, reviewed_at, is_ground_truth_clip, image_rel_path, label_rel_path)`. Includes `.to_dict()`.
- `DatasetManifest`: Immutable dataclass representing the full dataset manifest: `(dataset_version, created_at, config_hash, code_version, description, origin_description, class_mapping, split_ratios, split_counts, total_samples, total_boxes, groups_by_split, samples)`. Includes `.to_dict()` and `.to_json()`.
- `convert_box_to_yolo(x1, y1, x2, y2, frame_width, frame_height) -> tuple[float, float, float, float]`: Converts pixel bounding box coordinates to normalized YOLO center and dimensions $[x_c, y_c, w, h]$, enforcing non-inversion, non-zero dimensions, and clamping strictly within $[0.0, 1.0]$.
- `format_yolo_labels(annotations: Sequence[YoloAnnotation]) -> str`: Formats a sequence of YOLO annotations into newline-separated text file content.
- `parse_yolo_label_line(line: str) -> YoloAnnotation`: Parses a standard YOLO label line back into a `YoloAnnotation`.
- `assign_split_group_key(video_id, timestamp_s, strategy="time_block", time_block_duration_s=300.0) -> str`: Derives deterministic group identifier (`vid_<id>` or `vid_<id>_blk_<index>`) ensuring adjacent frames are assigned to the identical group.
- `split_groups_deterministic(group_ids, split_ratios=None, seed=42, ground_truth_group_ids=None, is_corrected_sample=True) -> dict[str, str]`: Deterministically assigns group IDs to splits (`'train'`, `'val'`, `'test'`) using seeded SHA-256 hashing. Guarantees:
  - **Group atomicity**: Every frame in a group receives the exact same split.
  - **Ground-truth clip protection**: Groups identified in `ground_truth_group_ids` NEVER enter `'train'`.
  - **Corrected sample protection**: Human-corrected reviews NEVER enter `'test'`.
- `deduplicate_frame_reviews(reviews_for_frame, policy="latest_review") -> list[Any]`: Deduplicates multiple reviews for the same video frame by object identity (`track_id` or `detection_id`), retaining the latest `reviewed_at` timestamp.
- `audit_split_leakage(samples, ground_truth_video_ids=None, ground_truth_segment_bounds=None) -> dict[str, Any]`: Verifies that no group spans multiple splits, no ground-truth clip is assigned to `'train'`, and no human-corrected sample is assigned to `'test'`.
- `generate_dataset_yaml(dataset_dir, class_mapping, splits_present=("train", "val")) -> str`: Generates standard Ultralytics YOLO `dataset.yaml` with root path, relative split image directories, and integer-to-class-name mapping.

### Active-Learning Dataset Service (`backend.services.dataset`)
- `build_active_learning_dataset(output_dir=None, dataset_version=None, run_id=None, video_id=None, split_ratios=None, split_strategy=None, time_block_duration_s=None, seed=None, min_frame_interval_s=None, export_images=True, config=None, repository_root=None, connection=None) -> dict[str, Any]`: Orchestrates end-to-end dataset generation from approved manual reviews. Queries approved reviews from `manual_reviews`, resolves effective classes and bounding boxes, groups frames by video or contiguous time block, excludes ground-truth evaluation clips from training, deterministically assigns splits, exports normalized `.txt` labels and extracted `.jpg` images, writes `dataset.yaml` and `manifest.json`, and audits leakage.
- `get_dataset_manifest(dataset_path: Path | str) -> dict[str, Any]`: Loads and parses `manifest.json` from a dataset directory or file path.
- `audit_dataset_leakage_from_path(manifest_or_dataset_path: Path | str | dict[str, Any], ground_truth_video_ids=None) -> dict[str, Any]`: Audits an existing dataset or manifest on disk for data leakage safety.

### Repository Operations (`backend.database.repository`)
- `fetch_approved_manual_reviews(connection: sqlite3.Connection, run_id: str | None = None, video_id: str | None = None) -> list[sqlite3.Row]`: Queries `manual_reviews` where `review_status = 'approved'` with optional `run_id` and `video_id` filtering.
- `fetch_ground_truth_segments(connection: sqlite3.Connection, video_id: str | None = None) -> list[sqlite3.Row]`: Queries video segments joined with `ground_truth_counts` and `ground_truth_sets` to identify held-out evaluation clips.
- `fetch_video_by_id(connection: sqlite3.Connection, video_id: str) -> sqlite3.Row | None`: Fetches a video record by `video_id` from the canonical `videos` table.

### FastAPI Application Endpoints (`backend.app`)
- `POST /datasets/export`: Accepts `ExportDatasetRequest`, executes dataset preparation, and returns `201 Created` with summary statistics, manifest path, and leakage audit.
- `GET /datasets/{dataset_version}/manifest`: Retrieves the manifest JSON for an exported dataset version or returns `404 Not Found`.
- `POST /datasets/audit-leakage`: Accepts `AuditDatasetLeakageRequest` with a dataset manifest path and returns the leakage verification report.
- Typed Pydantic request models: `ExportDatasetRequest`, `AuditDatasetLeakageRequest`.

### CLI Commands (`backend.cli`)
- `traffic-vision export-dataset [--output-dir DIR] [--version VERSION] [--run-id RUN_ID] [--video-id VIDEO_ID] [--split-strategy STRATEGY] [--train-ratio RATIO] [--val-ratio RATIO] [--seed SEED] [--no-images] [--config CONFIG]`: Exports YOLO-format dataset and outputs JSON summary.
- `traffic-vision show-dataset-manifest PATH [--config CONFIG]`: Inspects an exported dataset manifest and outputs formatted JSON.
- `traffic-vision audit-dataset-leakage PATH [--config CONFIG]`: Audits an exported dataset for split leakage and outputs verification JSON.

---

## 2. Changed and Created Files

| File | Status | Description |
|---|---|---|
| `prompts/phase_11_active_learning_dataset.md` | Authority | Revised in place to eliminate ambiguities: exact tables/columns, config keys with defaults, CLI/API interfaces, and measurable test plan TP11-01..TP11-16. |
| `configs/default.yaml` | Modified | Added default `active_learning` configuration section. |
| `backend/config.py` | Modified | Added `active_learning` section defaults to `DEFAULT_CONFIG` and validation logic in `_validate()`. |
| `backend/dataset.py` | Created | Pure dataset logic: `YoloAnnotation`, `DatasetSample`, `DatasetManifest`, coordinate conversions, group splitting, duplicate resolution, leakage auditing, and YAML formatting. |
| `backend/services/dataset.py` | Created | Active-learning dataset orchestration service: database aggregation, frame extraction, split assignment, YOLO exports, manifest generation, and leakage auditing. |
| `backend/database/repository.py` | Modified | Added additive queries: `fetch_approved_manual_reviews`, `fetch_ground_truth_segments`, and `fetch_video_by_id`. |
| `backend/cli.py` | Modified | Added additive CLI subcommands: `export-dataset`, `show-dataset-manifest`, `audit-dataset-leakage`. |
| `backend/app.py` | Modified | Added additive FastAPI routes and typed Pydantic models for active-learning dataset export, manifest inspection, and leakage audit. |
| `tests/test_dataset.py` | Created | Pure logic unit tests covering TP11-01, TP11-02, TP11-05, TP11-06, TP11-07, TP11-08, TP11-09, TP11-10, TP11-12, TP11-16. |
| `tests/test_dataset_service.py` | Created | Integration tests covering TP11-03 (approved review filtering), TP11-04 (correction precedence), TP11-11 (manifest provenance), TP11-13 (end-to-end service), TP11-14 (CLI commands), and ground-truth protection. |
| `tests/test_dataset_api.py` | Created | Integration tests covering TP11-15 (FastAPI dataset export, manifest retrieval, and leakage audit endpoints). |
| `docs/handoffs/phase_11/HANDOFF.md` | Created | This handoff document. |

---

## 3. Schema Usage and Invariants

**No database schema change was required.** All necessary tables and relationships already existed in `backend/database/schema.sql`:
- **`manual_reviews`**: Source of human-verified annotations (`review_status = 'approved'`).
- **`videos`**: Source of video geometry (`width`, `height`), filesystem location (`path`), and media fingerprint (`sha256`).
- **`video_segments` & `ground_truth_counts`**: Source of held-out evaluation clips to protect from training leakage.
- **`processing_runs`**: Preserves upstream run lineage and configuration provenance.

### Invariants Enforced
1. **Approval Invariant**: Only reviews with `review_status = 'approved'` enter exported datasets. Pending and rejected reviews are strictly discarded.
2. **Correction Precedence**: `corrected_class` overrides `original_class` when present; `corrected_bbox_json` overrides `original_bbox_json` when present.
3. **Group Atomicity**: Frames are grouped by video or contiguous time blocks (default 300 s). All frames in a group are assigned to the exact same split; adjacent frames are never split across train/val/test.
4. **Ground-Truth Evaluation Clip Safety**: Video frames falling within segments linked to `ground_truth_counts` or marked as evaluation clips NEVER enter the `'train'` split.
5. **Corrected Sample Safety**: Human-reviewed corrections NEVER enter the `'test'` split, preventing contamination of held-out benchmark evaluation.
6. **Provenance Integrity**: `manifest.json` permanently preserves source video SHA-256, run ID, frame number, timestamp, reviewer identifier, review ID, and reviewed timestamp for every exported sample.
7. **No Research Data Fabrication**: All test fixtures are synthetic software fixtures, explicitly labelled as such. No fake CCTV measurements or calibration points were invented.

---

## 4. Configuration Schema and Defaults

In `configs/default.yaml`:
```yaml
active_learning:
  output_dir: data/processed/datasets
  default_version: v1
  split_strategy: time_block  # "video" or "time_block"
  time_block_duration_s: 300.0
  split_ratios:
    train: 0.8
    val: 0.2
    test: 0.0
  seed: 42
  duplicate_policy: latest_review  # "latest_review" or "keep_all"
  class_mapping:
    car: 0
    bus: 1
    truck: 2
    motorcycle: 3
    auto_rickshaw: 4
  min_frame_interval_s: 0.0
  export_images: true
```

Validated in `backend/config.py`:
- `output_dir`: Non-empty string path (default `'data/processed/datasets'`).
- `default_version`: Non-empty string version identifier (default `'v1'`).
- `split_strategy`: Must be one of `'video'` or `'time_block'`.
- `time_block_duration_s`: Positive number $> 0$ (default 300.0 s).
- `split_ratios`: Mapping of split name to float $\in [0.0, 1.0]$, sum of weights $> 0$.
- `seed`: Integer seed for deterministic split assignment (default 42).
- `duplicate_policy`: Must be `'latest_review'` or `'keep_all'`.
- `class_mapping`: Non-empty mapping of class name strings to integer IDs $\ge 0$.
- `min_frame_interval_s`: Non-negative float $\ge 0.0$ defining temporal stride.
- `export_images`: Boolean indicating whether to decode and save `.jpg` images to disk.

---

## 5. Raw Test Results

### Full Pytest Suite (`uv run pytest -q`)
```text
........................................................................ [ 36%]
........................................................................ [ 73%]
....................................................                     [100%]
196 passed in 28.04s
```

### Focused Phase 11 Tests (`uv run pytest tests/test_dataset.py tests/test_dataset_service.py tests/test_dataset_api.py -v`)
```text
============================= test session starts =============================
platform win32 -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0 -- D:\Work\Personal\traffic-vision-final-year-project\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: D:\Work\Personal\traffic-vision-final-year-project
configfile: pyproject.toml
plugins: anyio-4.15.1
collecting ... collected 20 items

tests/test_dataset.py::test_tp11_01_box_to_yolo_conversion_accuracy PASSED [  5%]
tests/test_dataset.py::test_tp11_01_box_to_yolo_boundary_clamping_and_validation PASSED [ 10%]
tests/test_dataset.py::test_tp11_02_yolo_label_formatting_and_parsing PASSED [ 15%]
tests/test_dataset.py::test_tp11_05_group_based_split_by_video_leakage_safety PASSED [ 20%]
tests/test_dataset.py::test_tp11_06_group_based_split_by_time_block PASSED [ 25%]
tests/test_dataset.py::test_tp11_07_deterministic_seeded_splitting PASSED [ 30%]
tests/test_dataset.py::test_tp11_08_ground_truth_clip_training_exclusion PASSED [ 35%]
tests/test_dataset.py::test_tp11_09_corrected_sample_test_split_exclusion PASSED [ 40%]
tests/test_dataset.py::test_tp11_10_duplicate_review_handling PASSED     [ 45%]
tests/test_dataset.py::test_tp11_12_dataset_yaml_generation PASSED       [ 50%]
tests/test_dataset.py::test_tp11_16_configuration_validation PASSED      [ 55%]
tests/test_dataset_service.py::test_tp11_03_approved_review_filtering PASSED [ 60%]
tests/test_dataset_service.py::test_tp11_04_and_13_end_to_end_dataset_export PASSED [ 65%]
tests/test_dataset_service.py::test_tp11_11_manifest_provenance_verification PASSED [ 70%]
tests/test_dataset_service.py::test_tp11_14_cli_dataset_commands PASSED  [ 75%]
tests/test_dataset_service.py::test_tp11_ground_truth_segment_protection_service PASSED [ 80%]
tests/test_dataset_api.py::test_tp11_15_fastapi_export_dataset_endpoint PASSED [ 85%]
tests/test_dataset_api.py::test_tp11_15_fastapi_get_manifest_endpoint PASSED [ 90%]
tests/test_dataset_api.py::test_tp11_15_fastapi_audit_leakage_endpoint PASSED [ 95%]
tests/test_dataset_api.py::test_tp11_15_fastapi_export_error_when_no_reviews PASSED [100%]

============================= 20 passed in 4.30s ==============================
```

---

## 6. Assumptions and Limitations

1. **Frame Exactness**: Frame extraction uses OpenCV (`cv2.VideoCapture` set to `CAP_PROP_POS_FRAMES`). While reliable for fixed-FPS footage, variable-frame-rate DVR footage should rely on PTS timestamps where exact seek discrepancy exists.
2. **Offline Active Learning**: This phase exports versioned dataset artifacts to disk (`dataset.yaml`, `manifest.json`, `images/`, `labels/`). It does not trigger model retraining or evaluate model weights (owned by Phase 12).
3. **No Automatic Replacement**: Exporting a dataset does not update or replace any production model weights.

---

## 7. Next-Phase Dependencies (Phase 12: Model Fine-Tuning and Evaluation)

1. Phase 12 consumes `dataset.yaml` and versioned manifests produced by Phase 11.
2. Phase 12 will register trained candidate models into `model_versions` referencing `dataset_version`.
3. Phase 12 evaluates detection metrics (precision, recall, mAP) on the validation split and tracking/counting metrics against Phase 06 ground truth sets.
