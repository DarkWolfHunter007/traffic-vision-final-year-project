# Phase 07 Handoff — Camera Calibration and Diagnostics

## 1. Delivered Interfaces and Modules

### Pure Calibration Logic (`backend.calibration`)
- `CalibrationPoint`: Immutable dataclass representing a 2D correspondence `(image_x, image_y)` in pixels and `(world_x, world_y)` on the ground road plane in metres, with role `fit` or `held_out`.
- `CalibrationResult`: Diagnostic dataclass containing homography matrices $H$ and $H^{-1}$, point counts, mean and max reprojection error on held-out points, fit errors, acceptance boolean, distortion check status, flat-road assumption flag, and serialized `parameters_json`.
- `are_points_collinear(points_2d, eps=1e-4)`: Singular Value Decomposition (SVD) check for collinearity across arbitrary sets of 2D points.
- `three_points_collinear(p1, p2, p3, eps=1e-4)`: Normalized cross-product collinearity check for triplets of points.
- `is_collinear_or_degenerate(points, eps=1e-4)`: Comprehensive check verifying that reference points form a non-degenerate, rank-2 configuration in both image space and world space (and that no 3 of 4 minimal fit points are collinear).
- `validate_calibration_points(points, min_points=6, held_out_count=2)`: Validates input correspondences, verifies finiteness and distinctness, partitions points into `fit` and `held_out` sets (honouring explicit `role` tags or using deterministic hold-out), and enforces $\ge 4$ non-collinear fit points and $\ge 1$ held-out point.
- `compute_homography(fit_points)`: Computes $3 \times 3$ perspective transformation matrix $H$ (image $\to$ world) and $H^{-1}$ (world $\to$ image) using OpenCV Direct Linear Transformation, verifying condition and non-singularity ($\det(H) \neq 0$).
- `project_image_to_world(image_x, image_y, homography_matrix)`: Projects an image pixel coordinate $(u, v)$ to world metres $(X, Y)$ on the road plane, rejecting non-finite coordinates or points projecting to infinity ($w = 0$).
- `project_world_to_image(world_x, world_y, inverse_homography_matrix)`: Projects road world coordinates $(X, Y)$ in metres back to image coordinates $(u, v)$ in pixels.
- `project_points_image_to_world(points, homography_matrix)`: Vectorized batch transformation for $N \times 2$ coordinate arrays.
- `compute_reprojection_errors(points, homography_matrix)`: Calculates Euclidean reprojection error in metres $\sqrt{(\hat{X}_i - X_i)^2 + (\hat{Y}_i - Y_i)^2}$ for point sets.
- `calibrate_camera(points, config=None)`: Pure calibration pipeline returning `CalibrationResult`.

### Calibration Orchestration Service (`backend.services.calibration`)
- `load_calibration_points(file_path)`: Loads and parses point correspondences from YAML or JSON files, supporting top-level lists or `points: [...]` mappings.
- `run_calibration(parent_run_or_video_id, points_file_or_data, config, repository_root, connection=None)`: Orchestrates camera calibration against an ingestion run, tracking run, or video ID. Creates an immutable `processing_runs` record with full configuration snapshot and provenance, populates `calibration_runs` and `calibration_points`, and commits the transaction.
- `get_calibration(calibration_id, config=None, repository_root=None, connection=None)`: Retrieves stored calibration details, matrices, parameters, and point correspondences from the database.

### Repository Operations (`backend.database.repository`)
- `insert_calibration_run(connection, run)`: Inserts record into `calibration_runs`.
- `insert_calibration_points(connection, points)`: Batch inserts records into `calibration_points`.
- `fetch_calibration_run_by_id(connection, calibration_id)`: Fetches a calibration run by ID.
- `fetch_calibration_points_for_run(connection, calibration_id)`: Fetches point correspondences for a calibration ID.
- `fetch_calibration_runs_for_video(connection, video_id)`: Fetches all calibration runs associated with a video.
- `fetch_latest_accepted_calibration(connection, video_id)`: Fetches the latest accepted calibration run (`accepted = 1`) for a video.

### CLI Commands (`backend.cli`)
- `traffic-vision calibrate TARGET POINTS_FILE [--config CONFIG]`: Executes camera calibration for a parent run ID or video ID using reference points from a YAML/JSON file, outputting JSON summary with `calibration_id`, `run_id`, `accepted`, and reprojection errors.
- `traffic-vision show-calibration CALIBRATION_ID [--config CONFIG]`: Inspects a stored calibration run and outputs its matrices, diagnostic parameters, and point correspondences.

---

## 2. Changed and Created Files

| File | Status | Description |
|---|---|---|
| `prompts/phase_07_camera_calibration.md` | Modified | Audited and revised in place with exact schema tables/columns, config keys, interfaces, and test plan TP7-01..12. |
| `configs/default.yaml` | Modified | Added `calibration` configuration block with defaults. |
| `backend/config.py` | Modified | Added default calibration config and schema validation in `_validate()`. |
| `backend/database/repository.py` | Modified | Added repository CRUD functions for `calibration_runs` and `calibration_points`. |
| `backend/calibration.py` | Created | Pure planar homography calibration math, collinearity checks, and coordinate projections. |
| `backend/services/calibration.py` | Created | Service orchestrating calibration runs, database persistence, point loading, and inspection. |
| `backend/cli.py` | Modified | Added `calibrate` and `show-calibration` CLI subcommands and execution branches. |
| `tests/test_calibration.py` | Created | Unit tests for pure homography math, held-out evaluation, collinearity rejection, projections, and config validation. |
| `tests/test_calibration_service.py` | Created | Integration tests for database persistence, invariants, target resolution, and CLI commands. |
| `docs/handoffs/phase_07/HANDOFF.md` | Created | This handoff document. |

---

## 3. Schema Usage and Invariants

No schema changes were required. Canonical tables in `backend/database/schema.sql` are used strictly as designed:
- **`calibration_runs`**:
  - `calibration_id`: Primary key UUID.
  - `run_id`: References `processing_runs(run_id)`.
  - `video_id`: References `videos(video_id)`.
  - `method`: Projective method (`'planar_homography'`).
  - `point_count`: Total number of point correspondences supplied ($\ge 6$).
  - `held_out_point_count`: Number of validation points held out from fitting ($\ge 1$, default 2).
  - `reprojection_error_m_mean`: Mean error in metres on held-out validation points.
  - `reprojection_error_m_max`: Maximum error in metres on held-out validation points.
  - `distortion_checked`: Integer flag (0 or 1).
  - `flat_road_assumption`: Integer flag (1 for planar road assumption).
  - `accepted`: Integer flag (1 if held-out error $\le$ threshold, 0 if rejected).
  - `parameters_json`: Canonical JSON snapshot storing $H$, $H^{-1}$, fit errors, and metadata.
- **`calibration_points`**:
  - `calibration_point_id`: Primary key UUID.
  - `calibration_id`: Foreign key referencing `calibration_runs(calibration_id)`.
  - `role`: Role string (`'fit'` or `'held_out'`).
  - `image_x`, `image_y`: Image pixel coordinates.
  - `world_x`, `world_y`: Ground plane coordinates in metres.
- **`tracks` table invariant**:
  - `world_x`, `world_y` must remain `NULL` until an accepted calibration run is referenced via `calibration_id` (enforced by SQLite CHECK constraint `((world_x IS NULL AND world_y IS NULL) OR calibration_id IS NOT NULL)`).

---

## 4. Configuration Schema and Defaults

In `configs/default.yaml`:
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

Validated in `backend/config.py`:
- `method`: string, must be `'planar_homography'`.
- `min_points`: integer $\ge 6$.
- `held_out_count`: integer $\ge 1$, and `min_points - held_out_count >= 4`.
- `max_reprojection_error_m`: float/int $> 0.0$.
- `distortion_check_enabled`: boolean.
- `flat_road_assumption`: boolean, must be `true`.
- `coordinate_unit`: non-empty string (default `'meter'`).

---

## 5. Raw Test Results

Running `uv run pytest -q`:

```text
........................................................................ [ 60%]
................................................                         [100%]
120 passed in 10.30s
```

Running `uv run pytest tests/test_calibration.py tests/test_calibration_service.py -v`:

```text
============================= test session starts =============================
platform win32 -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0 -- D:\Work\Personal\traffic-vision-final-year-project\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: D:\Work\Personal\traffic-vision-final-year-project
configfile: pyproject.toml
plugins: anyio-4.15.1
collecting ... collected 14 items

tests/test_calibration.py::test_tp7_01_planar_homography_estimation_near_zero_error PASSED [  7%]
tests/test_calibration.py::test_tp7_02_held_out_error_evaluation PASSED  [ 14%]
tests/test_calibration.py::test_tp7_03_point_count_validation_rejects_insufficient_points PASSED [ 21%]
tests/test_calibration.py::test_tp7_04_held_out_partitioning_and_role_handling PASSED [ 28%]
tests/test_calibration.py::test_tp7_05_collinear_and_degenerate_points_rejected PASSED [ 35%]
tests/test_calibration.py::test_tp7_06_calibration_exceeding_threshold_is_rejected PASSED [ 42%]
tests/test_calibration.py::test_tp7_07_calibration_within_threshold_is_accepted PASSED [ 50%]
tests/test_calibration.py::test_tp7_10_coordinate_projections_and_inversion PASSED [ 57%]
tests/test_calibration.py::test_tp7_12_config_validation_enforces_constraints PASSED [ 64%]
tests/test_calibration_service.py::test_tp7_08_and_09_database_persistence_and_invariants PASSED [ 71%]
tests/test_calibration_service.py::test_tracks_world_coordinate_database_invariants PASSED [ 78%]
tests/test_calibration_service.py::test_run_calibration_from_yaml_file_and_get_calibration PASSED [ 85%]
tests/test_calibration_service.py::test_run_calibration_target_resolution_errors PASSED [ 92%]
tests/test_calibration_service.py::test_tp7_11_cli_calibration_commands PASSED [100%]

============================= 14 passed in 1.23s ==============================
```

All 106 prior tests plus 14 new Phase 07 tests passed (120 tests total).

---

## 6. Assumptions and Limitations

1. **Planar-Road Assumption**: Homography calibration models a single 2D plane ($Z = 0$). If road segments have significant elevation slope, grade changes, or flyovers, planar homography will have localized perspective distortions.
2. **Ground Contact Point**: Projections from image pixels to road world coordinates strictly require vehicle bottom-centre ground points (`ground_x`, `ground_y`) established in Phase 04. Vehicle bounding-box centres must never be used.
3. **No Fabricated Data**: Production calibration strictly requires user-supplied surveyed ground control points or site measurements. The test suite utilizes synthetic software test fixtures explicitly labelled as such.
4. **Lens Distortion**: Homography assumes pinhole/rectified imagery. If strong wide-angle barrel distortion exists, `distortion_checked` must be audited before treating calibration as accurate.

---

## 7. Dependencies for Phase 08 (Speed Observations)

- Phase 08 requires an accepted calibration run (`calibration_runs.accepted = 1`) to project bottom-centre vehicle ground points to world coordinates $(X, Y)$ in metres.
- Phase 08 consumes `project_image_to_world` or `project_points_image_to_world` from `backend.calibration`.
- Phase 08 populates `speed_observations` with foreign key `calibration_id` referencing `calibration_runs(calibration_id)`.

---

## 8. Independent Review Notice

In accordance with prompt instructions, this implementation model has run all phase tests and reported raw test results, but does not perform the final checks or declare the phase accepted. Final verification and review are reserved for independent review subagents.
