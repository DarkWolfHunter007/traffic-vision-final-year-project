# Phase 07 — Camera Calibration and Diagnostics

## Objective
Implement only validated planar homography calibration with held-out error diagnostics. This prompt is independently executable after the stated dependencies are complete.

## Master sections implemented
Calibration, Ground point and geometry (Sections 9, 10)

## Boundary
Implement nothing except this phase. Do not silently implement later-phase functionality.
Use `backend/database/schema.sql` and `docs/data_dictionary.md` as the canonical data contract.
Every derived/result row must retain `run_id` and relevant source video/frame/timestamp provenance.

## Scope
- Require user-supplied reference points only (no invented calibration points, ground truth, or measurements).
- Require at least six image/world point pairs (`min_points >= 6`). Four points with no independent error check are strictly insufficient.
- Partition points into fit points (at least 4 non-collinear pairs) and held-out test points (at least 1, default 2 points). Support explicit user role assignment (`fit` vs `held_out`) or deterministic selection.
- Reject degenerate, collinear, coincident, or non-finite point sets (e.g. points lying on a line, rank-deficient coordinates).
- Estimate planar perspective homography matrix $H$ mapping image pixels $(u, v)$ to ground world coordinates $(X, Y)$ in metres using fit points, and compute inverse homography $H^{-1}$.
- Evaluate reprojection error in metres on held-out test points: report mean (`reprojection_error_m_mean`) and maximum (`reprojection_error_m_max`).
- Also compute fit reprojection error for diagnostic logging in `parameters_json`.
- Reject calibration (`accepted = 0`) if held-out reprojection error exceeds configurable threshold `max_reprojection_error_m` (default 1.0 m). Mark `accepted = 1` only when held-out error is within threshold.
- Record `flat_road_assumption` (enforced 1) and wide-angle `distortion_checked` status (0 or 1).
- Persist calibration parameters and point roles into `calibration_runs` and `calibration_points`.
- Maintain project invariant: physical units and world coordinates (`world_x`, `world_y`) remain unavailable/invalid until an accepted calibration exists.
- Provide coordinate transformation helper functions for downstream speed (Phase 08) and queue (Phase 09) phases.

## Inputs and dependencies
- Phase 01: database connection, schema bootstrap, `videos`, `processing_runs`, provenance tracking.
- Phase 04: bottom-centre ground contact point convention (`ground_x`, `ground_y`).
- Reference points supplied via YAML or JSON file.

## Database schema and persistence
Prefer no schema change: canonical tables `calibration_runs` and `calibration_points` already exist in `backend/database/schema.sql`:
1. `calibration_runs`:
   - `calibration_id`: TEXT PRIMARY KEY
   - `run_id`: TEXT NOT NULL REFERENCES processing_runs(run_id)
   - `video_id`: TEXT NOT NULL REFERENCES videos(video_id)
   - `method`: TEXT NOT NULL (e.g. `'planar_homography'`)
   - `point_count`: INTEGER NOT NULL
   - `held_out_point_count`: INTEGER NOT NULL
   - `reprojection_error_m_mean`: REAL
   - `reprojection_error_m_max`: REAL
   - `distortion_checked`: INTEGER NOT NULL DEFAULT 0
   - `flat_road_assumption`: INTEGER NOT NULL DEFAULT 1
   - `accepted`: INTEGER NOT NULL DEFAULT 0
   - `parameters_json`: TEXT NOT NULL
2. `calibration_points`:
   - `calibration_point_id`: TEXT PRIMARY KEY
   - `calibration_id`: TEXT NOT NULL REFERENCES calibration_runs(calibration_id)
   - `role`: TEXT NOT NULL (`'fit'` or `'held_out'`)
   - `image_x`: REAL NOT NULL
   - `image_y`: REAL NOT NULL
   - `world_x`: REAL NOT NULL
   - `world_y`: REAL NOT NULL
3. `tracks` table invariant:
   - `world_x`, `world_y` must remain `NULL` until an accepted calibration run is referenced via `calibration_id`.

## Configuration
Add a `calibration` section to `configs/default.yaml` and validate it in `backend/config.py`:
```yaml
calibration:
  method: planar_homography
  min_points: 6
  held_out_count: 2
  max_reprojection_error_m: 1.0
  distortion_check_enabled: false
  flat_road_assumption: true
  coordinate_unit: meter
```
- `method`: string, must be `'planar_homography'`.
- `min_points`: integer $\ge 6$, minimum number of total reference points required.
- `held_out_count`: integer $\ge 1$, number of validation points held out from homography fitting (must satisfy `min_points - held_out_count >= 4`).
- `max_reprojection_error_m`: positive float/int, maximum acceptable reprojection error in metres (default 1.0).
- `distortion_check_enabled`: boolean (default `false`).
- `flat_road_assumption`: boolean, must be `true` for planar homography.
- `coordinate_unit`: string (default `'meter'`).

## Data and metadata
Use canonical field names from `backend/database/schema.sql` and `docs/data_dictionary.md`.
Preserve source video identity, source SHA-256, processing run provenance, model/configuration hash, and authoritative timestamps where applicable.
Four points with no independent error check are insufficient.
Never fabricate research data (no invented calibration points, ground truth, or measurements; use clearly-labelled software fixtures in tests only).

## Interface contract
- Pure logic module in `backend/calibration.py`:
  - `validate_calibration_points(points, min_points=6, held_out_count=2) -> tuple[list[dict], list[dict]]`
  - `is_collinear_or_degenerate(points, eps=1e-6) -> bool`
  - `compute_homography(fit_points) -> tuple[np.ndarray, np.ndarray]`
  - `project_image_to_world(image_x, image_y, homography_matrix) -> tuple[float, float]`
  - `project_world_to_image(world_x, world_y, inverse_homography_matrix) -> tuple[float, float]`
  - `compute_reprojection_errors(points, homography_matrix) -> list[float]`
  - `calibrate_camera(points, config) -> CalibrationResult`
- Calibration orchestration service in `backend/services/calibration.py`:
  - `run_calibration(parent_run_or_video_id, points_file_or_data, config, repository_root, connection=None) -> dict`
  - `load_calibration_points(file_path) -> list[dict]`
  - `get_calibration(calibration_id, config=None, repository_root=None, connection=None) -> dict | None`
- Repository operations in `backend/database/repository.py`:
  - `insert_calibration_run(connection, run_dict)`
  - `insert_calibration_points(connection, points_list)`
  - `fetch_calibration_run_by_id(connection, calibration_id)`
  - `fetch_calibration_points_for_run(connection, calibration_id)`
  - `fetch_calibration_runs_for_video(connection, video_id)`
  - `fetch_latest_accepted_calibration(connection, video_id)`
- CLI commands in `backend/cli.py`:
  - `traffic-vision calibrate RUN_OR_VIDEO_ID POINTS_FILE [--config CONFIG]`
  - `traffic-vision show-calibration CALIBRATION_ID [--config CONFIG]`

## Error handling
Reject or explicitly mark invalid inputs and failed processing:
- Reject non-existent parent runs or videos.
- Reject inputs with fewer than `min_points` point pairs (e.g. 4 or 5 points).
- Reject collinear, coincident, or degenerate point sets with an explicit descriptive error.
- Reject non-finite coordinates (`NaN`, `Inf`).
- When held-out reprojection error exceeds `max_reprojection_error_m`, store the run in `calibration_runs` with `accepted = 0` and report rejection; do not crash and do not mark as accepted.
- Do not silently drop records, invent measurements, or replace unavailable research values with zero.

## Tests and evidence
Add focused tests in `tests/test_calibration.py` and `tests/test_calibration_service.py`.
All existing tests and new phase tests must pass (`uv run pytest -q`).
Report raw pytest output in the handoff.
Test fixtures may be synthetic but must be clearly labelled as software fixtures.

## Handoff
Create `docs/handoffs/phase_07/HANDOFF.md` containing changed files, interfaces, schema changes, config keys/defaults, input/output contracts, raw test results, assumptions, limitations, unresolved issues, and dependencies for Phase 08.

## Completion criteria (measurable test plan TP7-01..TP7-12)
- **TP7-01**: Planar homography estimation on synthetic non-collinear points maps image points to ground-plane world coordinates with near-zero error.
- **TP7-02**: Held-out error calculation evaluates test points held out from fitting and reports mean and max reprojection error in metres.
- **TP7-03**: Point count validation rejects input with fewer than configured `min_points` (e.g. 4 or 5 points rejected).
- **TP7-04**: Held-out partitioning enforces at least 4 fit points and at least `held_out_count` test points; supports explicit `role` tags.
- **TP7-05**: Collinear point sets (e.g. 3+ points on a line in fit points, or all points on a line) are detected and rejected as degenerate.
- **TP7-06**: Calibration with reprojection error exceeding `max_reprojection_error_m` is marked `accepted = 0` (rejected) in database.
- **TP7-07**: Calibration with reprojection error within `max_reprojection_error_m` is marked `accepted = 1` (accepted).
- **TP7-08**: Invariants and flags (`flat_road_assumption = 1`, `distortion_checked`) are correctly recorded in `calibration_runs`.
- **TP7-09**: Persistence correctly writes to `calibration_runs` and `calibration_points` with proper foreign keys and roles (`fit`, `held_out`).
- **TP7-10**: Coordinate transformation helpers `project_image_to_world` and `project_world_to_image` correctly invert and reject non-finite inputs.
- **TP7-11**: CLI commands `traffic-vision calibrate` and `traffic-vision show-calibration` execute successfully and produce valid JSON outputs.
- **TP7-12**: Config validation enforces constraints on `calibration` section (method, min_points $\ge 6$, held_out_count, max_error > 0).

## Explicit exclusions
Speed observations (`speed_observations`), queue length (`queue_events`), counting changes, manual review, active learning, model training, emissions, MCE, SUMO.

## Independent review
Do not perform the final checks or acceptance review in this task. Prompt checking, implementation review, testing review, and completion verification will be performed separately by Pro subagents that are different from the normal implementation model.
Run your own phase tests and report raw output, but do not declare the phase accepted.