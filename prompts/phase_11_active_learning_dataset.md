# Phase 11 - Active-Learning Dataset Pipeline

## Objective
Implement only approved correction dataset generation with leakage-safe versioning. This prompt is independently executable after the stated dependencies are complete.

## Master sections implemented
Active Learning, Video Input, Preprocessing, Detection, Configuration, Provenance, Data Integrity, Out of scope, Phase gates (Sections 4, 5, 6, 7, 15, 16, 19, 21, 22).

## Boundary
Implement nothing except this phase. Do not silently implement later-phase functionality (e.g., model fine-tuning, training loops, evaluation metrics from Phase 12).
Use `backend/database/schema.sql` and `docs/data_dictionary.md` as the canonical data contract.
Every derived/result row and exported sample manifest must retain `run_id` and relevant source video/frame/timestamp provenance.
Only approved human corrections (`review_status = 'approved'`) from Phase 10 and explicitly selected video frames are included in exported datasets. Never fabricate labels or measurements.

## Scope
- Filter approved human review corrections:
  - Query `manual_reviews` where `review_status = 'approved'`.
  - Discard pending or rejected reviews.
  - Resolve effective bounding box geometry (`corrected_bbox_json` if present, else `original_bbox_json`) and effective class (`corrected_class` if present, else `original_class`).
  - Validate box geometry against frame dimensions and class label against configured `active_learning.class_mapping`.
- Frame selection and duplicate handling:
  - Group annotations per video frame `(video_id, frame_number)`.
  - Apply duplicate control policy (`latest_review` or `keep_all`) to resolve redundant reviews for the same track/detection on a frame.
  - Optional temporal sampling stride (`min_frame_interval_s`) to prevent redundant adjacent frames.
- Leakage-safe, deterministic grouping and splitting:
  - Group frames by source video or contiguous temporal block (`video_id` + time block, default 300 s), never by individual or adjacent frames.
  - Deterministically assign split groups using a seeded pseudo-random assignment (`active_learning.seed`, default 42) into configured split ratios (default 80% train, 20% val, 0% test).
  - Ground-truth evaluation clip safety: any video segment linked to `ground_truth_counts` or marked as a ground-truth evaluation clip in `video_segments` must NEVER enter the `train` split.
  - Corrected sample safety: human-reviewed corrections must never be placed into the `test` split (preventing contamination of held-out benchmark evaluation).
- YOLO format dataset generation:
  - Export normalized YOLO bounding boxes: `<class_id> <x_center> <y_center> <width> <height>` with coordinates in $[0.0, 1.0]$.
  - Directory structure: `images/train/`, `images/val/`, `images/test/`, `labels/train/`, `labels/val/`, `labels/test/`.
  - Frame image decoding: extract and save frames from source video using `cv2.VideoCapture` / media timeline when `export_images` is enabled.
  - Generate canonical `dataset.yaml` with dataset root, split relative paths, and integer-to-class-name mapping for Ultralytics YOLO consumption.
- Comprehensive manifest and provenance:
  - Write `manifest.json` recording `dataset_version`, UTC ISO timestamp `created_at`, configuration hash `config_hash`, Git commit `code_version`, split group assignments, class distribution counts, and per-sample provenance (`sample_id`, `video_id`, `source_video_sha256`, `run_id`, `frame_number`, `timestamp_s`, `split`, `split_group`, `review_ids`, `reviewers`, `reviewed_at`, `boxes`).
  - Document origin of the labelled set in manifest metadata.
- FastAPI application endpoints (`backend/app.py`):
  - `POST /datasets/export`: Trigger active-learning dataset export and return summary with manifest path.
  - `GET /datasets/{dataset_version}/manifest`: Retrieve manifest JSON for an exported dataset version.
  - `POST /datasets/audit-leakage`: Audit an exported dataset for split leakage and ground-truth contamination.
- CLI interface (`backend/cli.py`):
  - `traffic-vision export-dataset [--output-dir DIR] [--version VERSION] [--run-id RUN_ID] [--video-id VIDEO_ID] [--split-strategy STRATEGY] [--train-ratio RATIO] [--val-ratio RATIO] [--seed SEED] [--no-images] [--config CONFIG]`
  - `traffic-vision show-dataset-manifest PATH [--config CONFIG]`
  - `traffic-vision audit-dataset-leakage PATH [--config CONFIG]`

## Inputs and dependencies
- Phase 01: canonical database connection, schema bootstrap, `videos` (`video_id`, `path`, `sha256`, `width`, `height`), `video_frames`, `processing_runs`, provenance tracking, `backend.media`.
- Phase 06: `video_segments` (`segment_id`, `video_id`, `start_s`, `end_s`, `start_frame`, `end_frame`), `ground_truth_sets`, and `ground_truth_counts` for identifying held-out evaluation clips.
- Phase 10: manual review records (`manual_reviews` table: `review_id`, `run_id`, `video_id`, `track_id`, `detection_id`, `frame_number`, `timestamp_s`, `original_class`, `corrected_class`, `original_bbox_json`, `corrected_bbox_json`, `review_status`, `reviewer`, `reviewed_at`).

## Database schema and persistence
Prefer no schema change: canonical tables `manual_reviews`, `videos`, `video_segments`, `ground_truth_sets`, and `ground_truth_counts` already exist in `backend/database/schema.sql`:
- Query `manual_reviews` for `review_status = 'approved'`.
- Query `videos` for video dimensions (`width`, `height`), filesystem `path`, and `sha256`.
- Query `video_segments` and `ground_truth_counts` to identify and protect evaluation clips from training leakage.
- Dataset manifests (`manifest.json`), YOLO label files (`.txt`), extracted images (`.jpg`), and `dataset.yaml` are stored on disk under the configured dataset directory.

## Configuration
Add an `active_learning` section to `configs/default.yaml` and validate it in `backend/config.py`:
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
- `output_dir`: string path for saving generated datasets (default `'data/processed/datasets'`).
- `default_version`: string version identifier (default `'v1'`).
- `split_strategy`: string, one of `'video'` or `'time_block'` (default `'time_block'`).
- `time_block_duration_s`: float/int > 0 defining contiguous temporal segment length in seconds (default 300.0).
- `split_ratios`: mapping containing float ratios $\in [0.0, 1.0]$ for `train`, `val`, `test` summing to $1.0$ (or $> 0$). Default `train: 0.8, val: 0.2, test: 0.0`.
- `seed`: integer seed for deterministic split assignment (default 42).
- `duplicate_policy`: string, `'latest_review'` or `'keep_all'` (default `'latest_review'`).
- `class_mapping`: mapping of class name strings to non-negative integer IDs (default `car: 0, bus: 1, truck: 2, motorcycle: 3, auto_rickshaw: 4`).
- `min_frame_interval_s`: non-negative float $\ge 0.0$ defining minimum temporal gap between exported frames.
- `export_images`: boolean indicating whether to decode and save image files to disk (default true).

## Data and metadata
Use canonical field names from `backend/database/schema.sql` and `docs/data_dictionary.md`.
Preserve source video identity (`video_id`), source SHA-256 (`source_video_sha256`), processing run (`run_id`), reviewer (`reviewer`), review timestamp (`reviewed_at`), and authoritative timestamps (`timestamp_s`).
Every exported sample must retain complete linkage back to its source review and source video.
Never fabricate labels, calibration points, or ground truth (test fixtures must be clearly labelled software fixtures).

## Interface contract
- Pure logic module in `backend/dataset.py`:
  - `YoloAnnotation`: Dataclass representing normalized YOLO coordinates `(class_id, x_center, y_center, width, height)` with `.to_yolo_line()`.
  - `DatasetSample`: Dataclass representing an exported frame sample with source provenance and annotations.
  - `DatasetManifest`: Dataclass representing full dataset manifest with `.to_dict()` and `.to_json()`.
  - `convert_box_to_yolo(x1, y1, x2, y2, frame_width, frame_height) -> tuple[float, float, float, float]`: Converts pixel bbox to normalized $[x_c, y_c, w, h]$ clamped to $[0.0, 1.0]$.
  - `format_yolo_labels(annotations: Sequence[YoloAnnotation]) -> str`: Formats annotations into YOLO text file lines.
  - `assign_split_groups(items, strategy="time_block", time_block_duration_s=300.0) -> dict[str, list[Any]]`: Groups items by video or contiguous time block.
  - `split_groups_deterministic(group_ids, split_ratios={"train": 0.8, "val": 0.2}, seed=42, ground_truth_group_ids=None) -> dict[str, str]`: Deterministically assigns groups to splits while enforcing leakage and ground-truth safety constraints.
  - `deduplicate_frame_reviews(reviews_for_frame, policy="latest_review") -> list[ManualReview]`: Deduplicates multiple reviews for the same frame.
  - `generate_dataset_yaml(dataset_dir, class_mapping, splits_present) -> str`: Generates Ultralytics-compatible YAML content.
- Dataset preparation service in `backend/services/dataset.py`:
  - `build_active_learning_dataset(output_dir=None, dataset_version=None, run_id=None, video_id=None, split_ratios=None, split_strategy=None, time_block_duration_s=None, seed=None, min_frame_interval_s=None, export_images=True, config=None, repository_root=None, connection=None) -> dict[str, Any]`
  - `get_dataset_manifest(dataset_path: Path | str) -> dict[str, Any]`
  - `audit_dataset_leakage(manifest_or_dataset_path: Path | str | dict[str, Any], ground_truth_video_ids=None) -> dict[str, Any]`
- Repository operations in `backend/database/repository.py`:
  - `fetch_approved_manual_reviews(connection, run_id=None, video_id=None) -> list[sqlite3.Row]`
  - `fetch_ground_truth_segments(connection, video_id=None) -> list[sqlite3.Row]`
  - `fetch_video_by_id(connection, video_id) -> sqlite3.Row | None`
- FastAPI endpoints in `backend/app.py`:
  - `POST /datasets/export`: Typed request model `ExportDatasetRequest`, returns `DatasetExportResponse` (201 Created).
  - `GET /datasets/{dataset_version}/manifest`: Retrieves manifest JSON or returns 404.
  - `POST /datasets/audit-leakage`: Audits dataset for leakage and returns verification status.
- CLI commands in `backend/cli.py`:
  - `traffic-vision export-dataset [--output-dir DIR] [--version VERSION] [--run-id RUN_ID] [--video-id VIDEO_ID] [--split-strategy STRATEGY] [--train-ratio RATIO] [--val-ratio RATIO] [--seed SEED] [--no-images] [--config CONFIG]`
  - `traffic-vision show-dataset-manifest PATH [--config CONFIG]`
  - `traffic-vision audit-dataset-leakage PATH [--config CONFIG]`

## Error handling
Reject or explicitly mark invalid inputs and failed processing:
- Reject empty review candidate pools when exporting with an informative error.
- Reject invalid bounding boxes extending outside frame boundaries.
- Reject unmapped vehicle classes.
- Reject invalid split ratios (negative, all zeros).
- Detect and prevent split leakage: ensure no split group spans multiple splits.
- Enforce ground-truth safety: ensure no ground-truth clip frames enter the `train` split.
- Enforce corrected-sample safety: ensure no human-reviewed correction enters the `test` split.

## Tests and evidence
Add focused tests in:
- `tests/test_dataset.py`: Pure logic unit tests (box-to-YOLO conversion, normalized coordinate clamping, group-based assignment, deterministic seeded splitting, duplicate resolution, ground-truth exclusion).
- `tests/test_dataset_service.py`: Service orchestration, database querying, filesystem layout creation, YOLO label formatting, manifest provenance verification, leakage auditing, and CLI execution tests.
- `tests/test_dataset_api.py`: FastAPI dataset export, manifest retrieval, and leakage audit endpoint tests.
All existing tests and new phase tests must pass (`uv run pytest -q`).
Report raw pytest output in the handoff.
Test fixtures may be synthetic but must be clearly labelled as software fixtures.

## Handoff
Create `docs/handoffs/phase_11/HANDOFF.md` containing changed files, interfaces, schema changes, config keys/defaults, input/output contracts, raw test results, assumptions, limitations, unresolved issues, and dependencies for Phase 12.

## Completion criteria (measurable test plan TP11-01..TP11-16)
- **TP11-01**: Bounding box to YOLO coordinate conversion: Pixel coordinates $[x_1, y_1, x_2, y_2]$ on $W \times H$ image convert accurately to normalized $[x_c, y_c, w, h]$ in $[0.0, 1.0]$.
- **TP11-02**: YOLO label file formatting: Multiple annotations per frame format to standard YOLO text lines with correct integer class IDs.
- **TP11-03**: Approved review filtering: Only `manual_reviews` with `review_status = 'approved'` are included; pending and rejected reviews are excluded.
- **TP11-04**: Correction resolution: Human corrections (`corrected_class`, `corrected_bbox_json`) take precedence over original predictions when present.
- **TP11-05**: Group-based split assignment by video: All frames from the same video are assigned to the exact same split; no cross-split video leakage occurs.
- **TP11-06**: Group-based split assignment by time block: Frames within the same contiguous time block are assigned to the same split; no adjacent-frame leakage occurs across splits.
- **TP11-07**: Deterministic seeded splitting: Given the same seed and input groups, split assignment produces 100% identical split allocations.
- **TP11-08**: Ground-truth clip training exclusion: Video segments designated as ground-truth evaluation clips in `video_segments` / `ground_truth_counts` are never assigned to the `train` split.
- **TP11-09**: Corrected sample test exclusion: Human-corrected manual reviews are never placed into the `test` split.
- **TP11-10**: Duplicate review handling: Multiple reviews for the same frame are handled according to duplicate policy (e.g. latest review preserved).
- **TP11-11**: Full provenance in manifest: `manifest.json` preserves source video SHA-256, run_id, frame_number, timestamp_s, reviewer, review_id, and reviewed_at.
- **TP11-12**: Dataset directory structure and YAML: Dataset export produces valid `images/`, `labels/`, and `dataset.yaml` consumable by YOLO.
- **TP11-13**: End-to-end dataset generation service: `build_active_learning_dataset` runs against synthetic database fixture and produces complete dataset on disk.
- **TP11-14**: CLI dataset commands: `export-dataset`, `show-dataset-manifest`, and `audit-dataset-leakage` execute successfully and return valid JSON.
- **TP11-15**: FastAPI dataset endpoints: `POST /datasets/export`, `GET /datasets/{version}/manifest`, and `POST /datasets/audit-leakage` return appropriate HTTP responses.
- **TP11-16**: Configuration validation: `backend/config.py` validates all `active_learning` keys, types, split ratios, and policy options.

## Explicit exclusions
Candidate model training loops (Phase 12), tracking evaluation and mAP evaluation (Phase 12), active model production selection (Phase 12), emissions, MCE, redesign, SUMO.

## Independent review
Do not perform the final checks or acceptance review in this task. Prompt checking, implementation review, testing review, and completion verification will be performed separately by Pro subagents that are different from the normal implementation model.
Run your own phase tests and report raw output, but do not declare the phase accepted.