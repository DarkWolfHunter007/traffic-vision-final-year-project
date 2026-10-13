# Phase 10 - Manual Review and Human-in-the-Loop Correction

## Objective
Implement only uncertainty review, snippets, and auditable class/bounding-box corrections. This prompt is independently executable after the stated dependencies are complete.

## Master sections implemented
Manual Review, Preprocessing, Detection, Tracking, Configuration, Provenance, Data Integrity, Out of scope, Phase gates (Sections 4, 5, 6, 7, 8, 15, 19, 21, 22).

## Boundary
Implement nothing except this phase. Do not silently implement later-phase functionality.
Use `backend/database/schema.sql` and `docs/data_dictionary.md` as the canonical data contract.
Every derived/result row must retain `run_id` and relevant source video/frame/timestamp provenance.
Manual review must be append-only: never overwrite or delete original detections or tracks; corrections are stored in `manual_reviews` with reviewer, timestamp, original vs corrected values, and snippet path.

## Scope
- Identify configurable low-confidence and uncertain events:
  - Filter Phase 02 detections and Phase 03 tracks where confidence $\le \text{review.confidence_threshold}$ (default 0.50).
  - Support uncertainty classification reasons: `'low_confidence'`, `'class_ambiguity'`, `'boundary_drift'`, `'manual_flag'`.
  - Provide uncertainty candidate inspection without mutating existing records.
- Bounding box and class correction validation:
  - Validate bounding box geometry: finite numeric coordinates, $x_1 < x_2$ and $y_1 < y_2$, non-zero area ($w > 0, h > 0$).
  - Validate against video frame boundaries ($0 \le x_1, x_2 \le \text{frame\_width}$ and $0 \le y_1, y_2 \le \text{frame\_height}$). Reject out-of-frame edits.
  - Validate vehicle classes against configured `review.allowed_classes` (default `['car', 'bus', 'truck', 'motorcycle', 'auto_rickshaw']`). Reject disallowed or unknown vehicle classes.
- Auditable review lifecycle and append-only persistence:
  - Preserve original prediction class, confidence, and bounding box geometry verbatim in `original_class` and `original_bbox_json`.
  - Store corrections separately in `corrected_class` and `corrected_bbox_json`.
  - Constrain review statuses to `'pending'`, `'approved'`, `'rejected'` matching the canonical schema CHECK constraint.
  - Record reviewer identity (`reviewer`), authoritative UTC ISO timestamp (`reviewed_at`), and correction reason (`reason`).
  - Never overwrite or delete original `detections` or `tracks` rows.
- Event snippet generation:
  - Compute temporal boundaries $[ \max(0, \text{timestamp\_s} - \text{snippet\_before\_s}), \min(\text{duration\_s}, \text{timestamp\_s} + \text{snippet\_after\_s}) ]$ using configured before/after durations (default 1.0 s before, 1.0 s after).
  - Extract frames or encode video snippet to configured `review.output_dir` (default `data/processed/review_snippets`).
  - Save generated snippet file path in `manual_reviews.snippet_path`.
- FastAPI application endpoints (`backend/app.py`):
  - Expose typed review endpoints using Pydantic models for Phase 13 UI consumption:
    - `POST /reviews/candidates`: Identify and return uncertainty candidates for a run.
    - `POST /reviews`: Create a manual review item with validation and optional snippet generation.
    - `GET /reviews`: Query review items with filtering (`run_id`, `video_id`, `review_status`, `reviewer`, `track_id`, `detection_id`, `limit`).
    - `GET /reviews/{review_id}`: Retrieve a single review item.
    - `PATCH /reviews/{review_id}`: Update review status, reviewer, and/or corrections with validation.
    - `POST /reviews/{review_id}/snippet`: Generate snippet for an existing review item.
- CLI interface (`backend/cli.py`):
  - `traffic-vision find-review-candidates PARENT_RUN_ID [--confidence-threshold THRESH] [--limit LIMIT] [--config CONFIG]`
  - `traffic-vision create-review PARENT_RUN_ID --frame FRAME --timestamp TIME --reason REASON [--detection-id DET_ID] [--track-id TRACK_ID] [--reviewer REVIEWER] [--original-class CLASS] [--corrected-class CLASS] [--original-bbox BBOX_JSON] [--corrected-bbox BBOX_JSON] [--status STATUS] [--generate-snippet] [--config CONFIG]`
  - `traffic-vision show-reviews [--run-id RUN_ID] [--video-id VIDEO_ID] [--status STATUS] [--reviewer REVIEWER] [--limit LIMIT] [--config CONFIG]`
  - `traffic-vision update-review REVIEW_ID --status STATUS [--corrected-class CLASS] [--corrected-bbox BBOX_JSON] [--reviewer REVIEWER] [--config CONFIG]`
  - `traffic-vision generate-review-snippet REVIEW_ID [--config CONFIG]`

## Inputs and dependencies
- Phase 01: canonical database connection, schema bootstrap, `videos`, `video_frames`, `processing_runs`, provenance tracking, `media.py`, FastAPI application skeleton.
- Phase 02: detections (`detections` table: `detection_id`, `run_id`, `video_id`, `frame_number`, `timestamp_s`, `class_name`, `confidence`, `x1`, `y1`, `x2`, `y2`).
- Phase 03: tracking (`tracks` table: `track_observation_id`, `run_id`, `video_id`, `track_id`, `frame_number`, `timestamp_s`, `vehicle_class`, `confidence`, `x1`, `y1`, `x2`, `y2`).

## Database schema and persistence
Prefer no schema change: canonical table `manual_reviews` and index `idx_reviews_run` already exist in `backend/database/schema.sql`:
```sql
CREATE TABLE IF NOT EXISTS manual_reviews (
    review_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES processing_runs(run_id),
    video_id TEXT NOT NULL REFERENCES videos(video_id),
    track_id INTEGER,
    detection_id TEXT,
    frame_number INTEGER NOT NULL,
    timestamp_s REAL NOT NULL,
    original_class TEXT,
    corrected_class TEXT,
    original_bbox_json TEXT,
    corrected_bbox_json TEXT,
    reason TEXT NOT NULL,
    review_status TEXT NOT NULL CHECK (review_status IN ('pending', 'approved', 'rejected')),
    reviewer TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    snippet_path TEXT
);
```
- `review_id`: Stable text primary key (UUID).
- `run_id`: References `processing_runs(run_id)` of the evaluated run.
- `video_id`: References `videos(video_id)`.
- `track_id`: Nullable integer track identifier.
- `detection_id`: Nullable text detection identifier.
- `frame_number`: Integer frame index.
- `timestamp_s`: Authoritative media timestamp in seconds.
- `original_class`: Nullable original predicted vehicle class.
- `corrected_class`: Nullable human-corrected vehicle class.
- `original_bbox_json`: Nullable JSON string `{"x1": ..., "y1": ..., "x2": ..., "y2": ...}` of original bounding box.
- `corrected_bbox_json`: Nullable JSON string `{"x1": ..., "y1": ..., "x2": ..., "y2": ...}` of corrected bounding box.
- `reason`: Explanation for review / uncertainty (e.g. `'low_confidence'`, `'class_ambiguity'`, `'boundary_drift'`).
- `review_status`: Lifecycle status, constrained by CHECK constraint to `'pending'`, `'approved'`, or `'rejected'`.
- `reviewer`: Identifier of human reviewer or audit agent.
- `reviewed_at`: ISO 8601 UTC timestamp of review record creation or modification.
- `snippet_path`: Path to saved before/after snippet file.

## Configuration
Add a `review` section to `configs/default.yaml` and validate it in `backend/config.py`:
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
- `confidence_threshold`: float between 0.0 and 1.0; items with confidence $\le$ threshold are flagged for review (default 0.50).
- `snippet_before_s`: float/int $\ge 0.0$; time in seconds before event for snippet extraction (default 1.0 s).
- `snippet_after_s`: float/int $\ge 0.0$; time in seconds after event for snippet extraction (default 1.0 s).
- `allowed_classes`: list of non-empty strings defining valid vehicle classes for corrections.
- `review_statuses`: list of strings defining allowed review statuses (must match schema CHECK constraint `['pending', 'approved', 'rejected']`).
- `output_dir`: string path for saving generated review snippets (default `'data/processed/review_snippets'`).

## Data and metadata
Use canonical field names from `backend/database/schema.sql` and `docs/data_dictionary.md`.
Preserve source video identity, source SHA-256, processing run, model/configuration provenance, and authoritative timestamps where applicable.
Corrections must contain complete geometry (`x1, y1, x2, y2`) for downstream active learning and detection fine-tuning, not only a class label.
Never fabricate research data (no invented calibration points, ground truth, or measurements; use clearly-labelled software fixtures in tests only).

## Interface contract
- Pure logic module in `backend/review.py`:
  - `ReviewBox`: Dataclass representing bounding box coordinates `(x1, y1, x2, y2)` with `.to_dict()`, `.to_json()`, and `from_dict()`.
  - `UncertaintyCandidate`: Dataclass representing an identified uncertain detection or track observation.
  - `ManualReview`: Dataclass matching canonical `manual_reviews` table with `.to_dict()`.
  - `validate_bounding_box(bbox, frame_width=None, frame_height=None) -> ReviewBox`: Validates numeric validity, non-inversion, non-zero area, and frame boundary containment.
  - `validate_class_label(class_name, allowed_classes) -> str`: Validates vehicle class against allowed classes.
  - `validate_status_transition(current_status, new_status, allowed_statuses) -> str`: Validates review status lifecycle transitions.
  - `compute_snippet_window(timestamp_s, duration_s, before_s, after_s) -> tuple[float, float]`: Calculates clamped start/end timestamps.
  - `identify_uncertain_detections(detections, confidence_threshold) -> list[UncertaintyCandidate]`: Filters detections meeting uncertainty criteria.
  - `identify_uncertain_tracks(tracks, confidence_threshold) -> list[UncertaintyCandidate]`: Filters tracks meeting uncertainty criteria.
- Manual review service in `backend/services/review.py`:
  - `find_review_candidates(parent_run_id, confidence_threshold=None, limit=None, config=None, repository_root=None, connection=None) -> dict[str, Any]`
  - `create_manual_review(parent_run_id, frame_number, timestamp_s, reason, detection_id=None, track_id=None, reviewer="analyst", original_class=None, corrected_class=None, original_bbox=None, corrected_bbox=None, status="pending", generate_snippet=False, config=None, repository_root=None, connection=None) -> dict[str, Any]`
  - `get_manual_reviews(run_id=None, video_id=None, review_status=None, reviewer=None, track_id=None, detection_id=None, limit=None, config=None, repository_root=None, connection=None) -> dict[str, Any]`
  - `get_manual_review_by_id(review_id, config=None, repository_root=None, connection=None) -> dict[str, Any] | None`
  - `update_manual_review(review_id, status=None, corrected_class=None, corrected_bbox=None, reviewer=None, reason=None, config=None, repository_root=None, connection=None) -> dict[str, Any]`
  - `generate_snippet_for_review(review_id, config=None, repository_root=None, connection=None) -> Path`
- Repository operations in `backend/database/repository.py`:
  - `insert_manual_review(connection, review_row)`
  - `update_manual_review_record(connection, review_id, updates)`
  - `fetch_manual_reviews(connection, run_id=None, video_id=None, review_status=None, reviewer=None, track_id=None, detection_id=None, limit=None)`
  - `fetch_manual_review_by_id(connection, review_id)`
  - `fetch_detection_by_id(connection, detection_id)`
  - `fetch_track_observation_by_id(connection, track_observation_id)`
  - `fetch_manual_review_stats(connection, run_id=None)`
- FastAPI endpoints in `backend/app.py`:
  - `POST /reviews/candidates`: Typed request model `CandidateSearchRequest`, returns list of `UncertaintyCandidateResponse`.
  - `POST /reviews`: Typed request model `CreateReviewRequest`, returns `ManualReviewResponse` (201 Created).
  - `GET /reviews`: Query parameters with typed list response.
  - `GET /reviews/{review_id}`: Typed response or 404.
  - `PATCH /reviews/{review_id}`: Typed request model `UpdateReviewRequest`, returns updated `ManualReviewResponse`.
  - `POST /reviews/{review_id}/snippet`: Triggers snippet generation, returns snippet path.
- CLI commands in `backend/cli.py`:
  - `traffic-vision find-review-candidates PARENT_RUN_ID [--confidence-threshold THRESH] [--limit LIMIT] [--config CONFIG]`
  - `traffic-vision create-review PARENT_RUN_ID --frame FRAME --timestamp TIME --reason REASON [...] [--config CONFIG]`
  - `traffic-vision show-reviews [--run-id RUN_ID] [--video-id VIDEO_ID] [--status STATUS] [...] [--config CONFIG]`
  - `traffic-vision update-review REVIEW_ID --status STATUS [...] [--config CONFIG]`
  - `traffic-vision generate-review-snippet REVIEW_ID [--config CONFIG]`

## Error handling
Reject or explicitly mark invalid inputs and failed processing:
- Reject non-existent parent runs or non-completed parent runs when querying candidates.
- Reject out-of-frame bounding boxes ($x_1 < 0, y_1 < 0, x_2 > W, y_2 > H$) with clear validation error.
- Reject inverted or zero-area bounding boxes ($x_1 \ge x_2, y_1 \ge y_2$).
- Reject disallowed vehicle classes not present in `allowed_classes`.
- Reject invalid status strings not matching `'pending'`, `'approved'`, or `'rejected'`.
- Strict append-only invariant: Never update, modify, or delete rows in `detections` or `tracks`.

## Tests and evidence
Add focused tests in:
- `tests/test_review.py`: Pure logic unit tests (uncertainty candidate filtering, bbox validation, class validation, status transitions, snippet window calculations).
- `tests/test_review_service.py`: Service orchestration, database persistence, snippet file creation, and CLI execution tests.
- `tests/test_review_api.py`: FastAPI endpoints integration tests with `httpx` async / test client.
All existing tests and new phase tests must pass (`uv run pytest -q`).
Report raw pytest output in the handoff.
Test fixtures may be synthetic but must be clearly labelled as software fixtures.

## Handoff
Create `docs/handoffs/phase_10/HANDOFF.md` containing changed files, interfaces, schema changes, config keys/defaults, input/output contracts, raw test results, assumptions, limitations, unresolved issues, and dependencies for Phase 11.

## Completion criteria (measurable test plan TP10-01..TP10-16)
- **TP10-01**: Uncertainty candidate selection: Detections and tracks with confidence $\le \text{confidence\_threshold}$ are flagged; items with confidence above threshold are not flagged.
- **TP10-02**: Custom threshold candidate selection: Passing an explicit threshold parameter correctly overrides the config default.
- **TP10-03**: Bounding box geometry validation: Valid in-frame box coordinates pass validation and are normalized as `ReviewBox`.
- **TP10-04**: Out-of-frame bounding box rejection: Box coordinates extending outside $[0, W] \times [0, H]$ are rejected.
- **TP10-05**: Inverted and zero-area bounding box rejection: Boxes with $x_1 \ge x_2$ or $y_1 \ge y_2$ are rejected.
- **TP10-06**: Allowed vehicle class validation: Valid classes from `review.allowed_classes` are accepted; unknown classes are rejected.
- **TP10-07**: Preservation of original predictions: Original class, confidence, and bounding box are recorded verbatim in `original_class` and `original_bbox_json`.
- **TP10-08**: Append-only invariant: Creating and updating reviews never modifies or deletes rows in `detections` or `tracks` tables.
- **TP10-09**: Review status lifecycle transitions: Valid transitions between `'pending'`, `'approved'`, and `'rejected'` succeed; invalid status strings are rejected.
- **TP10-10**: Snippet temporal boundary clamping: Temporal window $[t - \text{before}, t + \text{after}]$ is clamped to $[0, \text{duration\_s}]$.
- **TP10-11**: Snippet generation file output: Snippet generation creates a video clip in `review.output_dir` and saves its path in `snippet_path`.
- **TP10-12**: Database persistence and query filters: `manual_reviews` rows persist with full provenance; queries correctly filter by `run_id`, `video_id`, `review_status`, and `reviewer`.
- **TP10-13**: FastAPI review endpoints: `POST /reviews`, `GET /reviews`, `PATCH /reviews/{id}`, and `POST /reviews/candidates` return typed responses with appropriate HTTP status codes.
- **TP10-14**: FastAPI validation error responses: Out-of-frame boxes or invalid classes submitted to the API return 422/400 validation errors.
- **TP10-15**: CLI commands end-to-end: `find-review-candidates`, `create-review`, `show-reviews`, and `update-review` execute successfully and output valid JSON.
- **TP10-16**: Configuration validation: `backend/config.py` validates all `review` section keys, types, and constraints.

## Explicit exclusions
Active learning dataset splitting (Phase 11), model retraining (Phase 12), full dashboard UI (Phase 13), emissions, MCE, redesign, SUMO.

## Independent review
Do not perform the final checks or acceptance review in this task. Prompt checking, implementation review, testing review, and completion verification will be performed separately by Pro subagents that are different from the normal implementation model.
Run your own phase tests and report raw output, but do not declare the phase accepted.