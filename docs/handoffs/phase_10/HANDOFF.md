# Phase 10 Handoff — Manual Review and Human-in-the-Loop Correction

## 1. Delivered Interfaces and Modules

### Pure Review Logic (`backend.review`)
- `ReviewBox`: Immutable dataclass representing pixel bounding boxes `(x1, y1, x2, y2)`. Includes `.to_dict()`, `.to_json()`, `from_dict()`, `from_json()`, and properties `width`, `height`, and `area`.
- `UncertaintyCandidate`: Immutable dataclass representing an uncertain detection or track observation flagged for human review matching `(candidate_id, source_type, item_id, track_id, frame_number, timestamp_s, predicted_class, confidence, bbox, reason)`. Includes `.to_dict()`.
- `ManualReview`: Immutable dataclass matching canonical `manual_reviews` table in `backend/database/schema.sql`: `(review_id, run_id, video_id, track_id, detection_id, frame_number, timestamp_s, original_class, corrected_class, original_bbox_json, corrected_bbox_json, reason, review_status, reviewer, reviewed_at, snippet_path)`. Includes `.to_dict()`.
- `validate_bounding_box(bbox, frame_width=None, frame_height=None)`: Validates bounding box coordinates for numeric finiteness (rejects NaN/Inf), strictly non-negative values, non-inversion ($x_1 < x_2$, $y_1 < y_2$), non-zero area, and frame boundary containment ($0 \le x_1, x_2 \le \text{frame\_width}$, $0 \le y_1, y_2 \le \text{frame\_height}$). Rejects out-of-frame edits with explicit `ValueError`.
- `validate_class_label(class_name, allowed_classes=None)`: Enforces vehicle class membership against configured `review.allowed_classes`. Rejects disallowed or empty class names.
- `validate_status_transition(current_status, new_status, allowed_statuses=("pending", "approved", "rejected"))`: Enforces valid status strings matching the canonical schema CHECK constraint.
- `compute_snippet_window(timestamp_s, duration_s=None, before_s=1.0, after_s=1.0)`: Calculates before/after temporal window $[ \max(0, \text{timestamp\_s} - \text{before\_s}), \min(\text{duration\_s}, \text{timestamp\_s} + \text{after\_s}) ]$ clamped to non-negative time and video duration.
- `identify_uncertain_detections(detections, confidence_threshold=0.50)`: Identifies detections with confidence $\le \text{confidence\_threshold}$ and formats them as `UncertaintyCandidate` records.
- `identify_uncertain_tracks(tracks, confidence_threshold=0.50)`: Identifies track observations with confidence $\le \text{confidence\_threshold}$ and formats them as `UncertaintyCandidate` records.

### Manual Review Service (`backend.services.review`)
- `find_review_candidates(parent_run_id, confidence_threshold=None, limit=None, config=None, repository_root=None, connection=None)`: Retrieves detections and tracks for a completed parent run, identifies uncertainty candidates, and sorts them deterministically by media timestamp.
- `create_manual_review(parent_run_id, frame_number, timestamp_s, reason, detection_id=None, track_id=None, reviewer="analyst", original_class=None, corrected_class=None, original_bbox=None, corrected_bbox=None, status="pending", generate_snippet=False, config=None, repository_root=None, connection=None)`: Creates an append-only manual review record. Resolves original prediction and bounding box from detections/tracks if omitted. Enforces geometric validity against frame boundaries and allowed classes. Optionally generates an event video snippet clip. Never alters or deletes original detections or tracks.
- `get_manual_reviews(run_id=None, video_id=None, review_status=None, reviewer=None, track_id=None, detection_id=None, limit=None, config=None, repository_root=None, connection=None)`: Queries persisted reviews with composable filters.
- `get_manual_review_by_id(review_id, config=None, repository_root=None, connection=None)`: Retrieves a single manual review record by ID.
- `update_manual_review(review_id, status=None, corrected_class=None, corrected_bbox=None, reviewer=None, reason=None, config=None, repository_root=None, connection=None)`: Updates review status, reviewer, and/or corrections with geometric validation and an updated UTC `reviewed_at` timestamp.
- `generate_snippet_for_review(review_id, config=None, repository_root=None, connection=None)`: Generates a video snippet clip spanning $[t - \text{before}, t + \text{after}]$ for an existing review record and updates `manual_reviews.snippet_path`.
- `create_snippet_file(video_path, timestamp_s, output_path, before_s=1.0, after_s=1.0, duration_s=None, width=None, height=None, fps=30.0)`: Low-level media utility extracting video frames within the temporal window and encoding an MP4 video clip to disk.

### Repository Operations (`backend.database.repository`)
- `insert_manual_review(connection, review)`: Inserts a review row into canonical `manual_reviews` table.
- `update_manual_review_record(connection, review_id, updates)`: Updates fields of a review record by `review_id`.
- `fetch_manual_reviews(connection, run_id=None, video_id=None, review_status=None, reviewer=None, track_id=None, detection_id=None, limit=None)`: Fetches manual review rows with composable filters.
- `fetch_manual_review_by_id(connection, review_id)`: Fetches single review by `review_id`.
- `fetch_detection_by_id(connection, detection_id)`: Fetches single detection by `detection_id`.
- `fetch_track_observation_by_id(connection, track_observation_id)`: Fetches single track observation by `track_observation_id`.
- `fetch_manual_review_stats(connection, run_id=None)`: Aggregates summary statistics for reviews (total, pending, approved, rejected, class corrections count, bbox corrections count, snippet count).

### FastAPI Application Endpoints (`backend.app`)
- `POST /reviews/candidates`: Accepts `CandidateSearchRequest`, returns identified uncertainty candidates.
- `POST /reviews`: Accepts `CreateReviewRequest`, validates bounding box geometry and allowed classes, returns `201 Created` with created `ManualReview` record.
- `GET /reviews`: Queries review records with query parameter filters (`run_id`, `video_id`, `review_status`, `reviewer`, `track_id`, `detection_id`, `limit`).
- `GET /reviews/{review_id}`: Retrieves a single review item or returns `404 Not Found`.
- `PATCH /reviews/{review_id}`: Accepts `UpdateReviewRequest`, validates corrections, and returns updated review record.
- `POST /reviews/{review_id}/snippet`: Triggers snippet extraction for a review item, returning the saved snippet file path.
- Typed Pydantic request models: `BoundingBoxModel`, `CandidateSearchRequest`, `CreateReviewRequest`, `UpdateReviewRequest`.

### CLI Commands (`backend.cli`)
- `traffic-vision find-review-candidates PARENT_RUN_ID [--confidence-threshold THRESH] [--limit LIMIT] [--config CONFIG]`: Identifies uncertain detections and tracks flagged for review.
- `traffic-vision create-review PARENT_RUN_ID --frame FRAME --timestamp TIME --reason REASON [--detection-id DET_ID] [--track-id TRACK_ID] [--reviewer REVIEWER] [--original-class CLASS] [--corrected-class CLASS] [--original-bbox BBOX] [--corrected-bbox BBOX] [--status STATUS] [--generate-snippet] [--config CONFIG]`: Creates an auditable review/correction record.
- `traffic-vision show-reviews [--run-id RUN_ID] [--video-id VIDEO_ID] [--status STATUS] [--reviewer REVIEWER] [--limit LIMIT] [--config CONFIG]`: Queries and inspects review records.
- `traffic-vision update-review REVIEW_ID --status STATUS [--corrected-class CLASS] [--corrected-bbox BBOX] [--reviewer REVIEWER] [--config CONFIG]`: Updates review status or human corrections.
- `traffic-vision generate-review-snippet REVIEW_ID [--config CONFIG]`: Extracts and saves event snippet video clip.

---

## 2. Changed and Created Files

| File | Status | Description |
|---|---|---|
| `prompts/phase_10_manual_review.md` | Authority | Revised in place to eliminate ambiguities, define exact tables/columns, config keys with defaults, CLI/API interfaces, and measurable test plan TP10-01..TP10-16. |
| `docs/data_dictionary.md` | Modified | Added canonical entity specification for Phase 10 `manual_reviews`. |
| `configs/default.yaml` | Modified | Added default `review` section configuration. |
| `backend/config.py` | Modified | Added `review` section defaults to `DEFAULT_CONFIG` and validation logic in `_validate()`. |
| `backend/review.py` | Created | Pure review logic: `ReviewBox`, `UncertaintyCandidate`, `ManualReview`, bounding box geometry validation, class enforcement, status transitions, and snippet window calculations. |
| `backend/services/review.py` | Created | Manual review service orchestrating candidate search, validation, persistence, queries, updates, and snippet extraction. |
| `backend/database/repository.py` | Modified | Added additive CRUD, query, and statistics functions for `manual_reviews`. |
| `backend/cli.py` | Modified | Added additive review CLI subcommands (`find-review-candidates`, `create-review`, `show-reviews`, `update-review`, `generate-review-snippet`) and execution branches. |
| `backend/app.py` | Modified | Added additive FastAPI routes and typed Pydantic models for manual review operations. |
| `tests/test_review.py` | Created | Pure logic unit tests covering TP10-01..07, TP10-09, TP10-10, TP10-16, geometry validation, class enforcement, and edge cases. |
| `tests/test_review_service.py` | Created | Integration tests covering TP10-08 (append-only invariant), TP10-11 (snippet generation), TP10-12 (persistence and filtering), and TP10-15 (CLI end-to-end). |
| `tests/test_review_api.py` | Created | Integration tests covering TP10-13 (FastAPI review CRUD endpoints) and TP10-14 (FastAPI 422/404 validation error responses). |
| `docs/handoffs/phase_10/HANDOFF.md` | Created | This handoff document. |

---

## 3. Schema Usage and Invariants

No database schema changes were required. Canonical table `manual_reviews` in `backend/database/schema.sql` was utilized strictly as defined:
- **`manual_reviews`**:
  - `review_id`: Text primary key (UUID).
  - `run_id`: References `processing_runs(run_id)`.
  - `video_id`: References `videos(video_id)`.
  - `track_id`: Nullable integer track identifier.
  - `detection_id`: Nullable text detection identifier referencing `detections(detection_id)`.
  - `frame_number`: Integer frame index.
  - `timestamp_s`: Authoritative media presentation timestamp in seconds.
  - `original_class`: Nullable original predicted vehicle class label.
  - `corrected_class`: Nullable human-corrected vehicle class label.
  - `original_bbox_json`: Nullable JSON string `{"x1": ..., "y1": ..., "x2": ..., "y2": ...}` of original bounding box.
  - `corrected_bbox_json`: Nullable JSON string `{"x1": ..., "y1": ..., "x2": ..., "y2": ...}` of corrected bounding box.
  - `reason`: Explanation for review (e.g. `'low_confidence'`, `'class_ambiguity'`, `'boundary_drift'`).
  - `review_status`: Lifecycle status, constrained by CHECK constraint `CHECK (review_status IN ('pending', 'approved', 'rejected'))`.
  - `reviewer`: Identifier of human reviewer or audit agent.
  - `reviewed_at`: ISO 8601 UTC timestamp of review record creation or modification.
  - `snippet_path`: Path to saved before/after snippet file.
- **Append-Only Invariant**: Creating and updating reviews never mutates or deletes rows in `detections` or `tracks`. Original predictions and bounding boxes remain intact in upstream tables.
- **Geometry Invariants**: Bounding box edits are validated against video frame dimensions $[0, W] \times [0, H]$. Out-of-frame coordinates, inverted coordinates ($x_1 \ge x_2, y_1 \ge y_2$), negative coordinates, and non-finite values (NaN, Inf) are strictly rejected.
- **Class Label Invariants**: Corrected classes are validated against configured `review.allowed_classes`. Unknown classes are strictly rejected.

---

## 4. Configuration Schema and Defaults

In `configs/default.yaml`:
```yaml
review:
  confidence_threshold: 0.50
  snippet_before_s: 1.0
  snippet_after_s: 1.0
  allowed_classes:
    - car
    - bus
    - truck
    - motorcycle
    - auto_rickshaw
  review_statuses:
    - pending
    - approved
    - rejected
  output_dir: data/processed/review_snippets
```

Validated in `backend/config.py`:
- `confidence_threshold`: float between 0.0 and 1.0 (default 0.50).
- `snippet_before_s`: float/int $\ge 0.0$ (default 1.0 s).
- `snippet_after_s`: float/int $\ge 0.0$ (default 1.0 s).
- `allowed_classes`: list of non-empty strings (default `['car', 'bus', 'truck', 'motorcycle', 'auto_rickshaw']`).
- `review_statuses`: list of non-empty strings containing at least `'pending'`, `'approved'`, and `'rejected'`.
- `output_dir`: non-empty string path (default `'data/processed/review_snippets'`).

---

## 5. Raw Test Results

### Full Pytest Suite (`uv run pytest -q`)
```text
........................................................................ [ 40%]
........................................................................ [ 81%]
................................                                         [100%]
176 passed in 26.31s
```

### Focused Phase 10 Tests (`uv run pytest tests/test_review.py tests/test_review_service.py tests/test_review_api.py -v`)
```text
============================= test session starts =============================
platform win32 -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0 -- D:\Work\Personal\traffic-vision-final-year-project\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: D:\Work\Personal\traffic-vision-final-year-project
configfile: pyproject.toml
plugins: anyio-4.15.1
collecting ... collected 18 items

tests/test_review.py::test_tp10_01_uncertainty_candidate_selection_by_confidence_threshold PASSED [  5%]
tests/test_review.py::test_tp10_02_custom_confidence_threshold_candidate_selection PASSED [ 11%]
tests/test_review.py::test_tp10_03_bounding_box_geometry_validation PASSED [ 16%]
tests/test_review.py::test_tp10_04_out_of_frame_bounding_box_rejection PASSED [ 22%]
tests/test_review.py::test_tp10_05_inverted_and_zero_area_bounding_box_rejection PASSED [ 27%]
tests/test_review.py::test_tp10_06_allowed_vehicle_class_validation PASSED [ 33%]
tests/test_review.py::test_tp10_07_preservation_of_original_predictions PASSED [ 38%]
tests/test_review.py::test_tp10_09_review_status_lifecycle_transitions PASSED [ 44%]
tests/test_review.py::test_tp10_10_snippet_temporal_boundary_clamping PASSED [ 50%]
tests/test_review.py::test_tp10_16_config_validation_enforces_review_parameters PASSED [ 55%]
tests/test_review.py::test_identify_uncertain_tracks PASSED              [ 61%]
tests/test_review_service.py::test_tp10_08_append_only_invariant_preserves_detections_and_tracks PASSED [ 66%]
tests/test_review_service.py::test_tp10_11_snippet_generation_file_output PASSED [ 72%]
tests/test_review_service.py::test_tp10_12_database_persistence_and_query_filters PASSED [ 77%]
tests/test_review_service.py::test_tp10_15_cli_commands_end_to_end PASSED [ 83%]
tests/test_review_service.py::test_candidate_search_rejects_missing_or_incomplete_parent_run PASSED [ 88%]
tests/test_review_api.py::test_tp10_13_fastapi_review_endpoints_crud PASSED [ 94%]
tests/test_review_api.py::test_tp10_14_fastapi_validation_error_responses PASSED [100%]

============================= 18 passed in 3.63s ==============================
```

All 158 previously passing tests plus 18 new Phase 10 tests passed (176 tests total).

---

## 6. Assumptions and Limitations

1. **Append-Only Invariant**: In strict accordance with the master contract, human reviews and corrections do not overwrite or delete rows in `detections` or `tracks`. Downstream phases (such as Phase 11 active learning) query `manual_reviews` for verified annotations while preserving original model inference rows.
2. **Offline CCTV Pipeline**: Manual reviews operate on ingested video footage and completed processing runs. No real-time camera streaming or external telemetry is assumed.
3. **No Retraining or Splitting**: Automatic fine-tuning/retraining (Phase 12) and train/val/test dataset splitting (Phase 11) are strictly outside Phase 10 scope.
4. **No Fabricated Data**: All test fixtures are synthetic software fixtures explicitly labelled as software fixtures. No fake research observations or calibration points were invented.

---

## 7. Dependencies for Phase 11

- Phase 11 (Active Learning & Dataset Splitting) consumes approved records from `manual_reviews` where `review_status = 'approved'` along with complete bounding box geometry (`corrected_bbox_json`) and vehicle classes (`corrected_class`) to produce fine-tuning datasets and leakage-safe video/segment-based splits.

---

## 8. Independent Review Notice

In accordance with prompt instructions, this implementation model has run all phase tests and reported raw test results, but does not perform the final checks or declare the phase accepted. Final verification and review are reserved for independent review subagents.
