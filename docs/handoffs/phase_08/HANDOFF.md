# Phase 08 Handoff — Speed Estimation

## 1. Delivered Interfaces and Modules

### Pure Speed Logic (`backend.speed`)
- `SpeedObservation`: Immutable dataclass representing a single calibrated speed observation matching the canonical `speed_observations` table: `speed_observation_id`, `run_id`, `video_id`, `track_id`, `timestamp_s`, `speed_mps`, `speed_kmh`, `calibration_id`, `status` (`'valid'`, `'invalid'`, `'unavailable'`), `smoothing_window`, `ground_point_method` (`'bottom_center'`), `world_x`, `world_y`. Includes `.to_dict()` for database persistence.
- `mps_to_kmh(speed_mps)`: Exact conversion from metres per second to kilometres per hour ($\times 3.6$, rounded to 4 decimals).
- `kmh_to_mps(speed_kmh)`: Exact conversion from kilometres per hour to metres per second ($/ 3.6$, rounded to 4 decimals).
- `smooth_trajectory_positions(points, window_s=0.5, max_gap_s=1.0)`: Deterministic centered moving-average smoothing of world coordinates $(X, Y)$ within a temporal window $W$ across continuous observations without bridging temporal gaps $> \text{max\_gap\_s}$.
- `estimate_speeds_for_trajectory(trajectory, homography_matrix, calibration_id, run_id, config=None)`: Pure speed calculation for a Phase 04 `Trajectory`:
  - Transforms bottom-centre ground contact points `(ground_x, ground_y)` into ground-plane world coordinates $(X, Y)$ in metres via planar homography $H$ from Phase 07.
  - Enforces `ground_point_method = 'bottom_center'`; bounding-box centres are strictly rejected.
  - Uses authoritative decoder media timestamps (`timestamp_s` / `pts_s`), never nominal FPS.
  - Applies position smoothing if `smoothing_method == 'moving_average'` and `smoothing_window_s > 0`.
  - Flags initial track observation ($i = 0$) as `status = 'unavailable'` (no preceding time interval $\Delta t$).
  - Flags non-monotonic or zero timestamps ($\Delta t \le 0$) as `status = 'invalid'`.
  - Flags observation gaps ($\Delta t > \text{max_gap_seconds}$) as `status = 'unavailable'`.
  - Flags short tracks ($< \text{min_track_points}$) as `status = 'unavailable'`.
  - Distinguishes stationary vehicles from sensor noise: displacements $\Delta d < \text{min_displacement_m}$ evaluate to valid speed 0.0 m/s (0.0 km/h) rather than phantom movement.
  - Flags implausible speed jumps ($v > \text{max_plausible_speed_mps}$) as `status = 'invalid'`.
  - Sets `speed_mps = None` and `speed_kmh = None` whenever status is `'unavailable'` or `'invalid'`; never fabricates zero or default measurements for missing research values.
- `estimate_speeds_for_trajectories(trajectories, homography_matrix, calibration_id, run_id, config=None)`: Batch wrapper applying speed estimation across a collection of trajectories.

### Speed Estimation Service (`backend.services.speed`)
- `run_speed_estimation(parent_run_id, calibration_id=None, config=None, repository_root=None, connection=None)`: Orchestrates speed estimation for a completed tracking parent run. Validates calibration acceptance (`calibration_runs.accepted = 1`), automatically resolves latest accepted calibration if `calibration_id` is omitted, creates a child `processing_runs` record with full provenance, reconstructs trajectories via Phase 04 `build_trajectories()`, calculates speeds, persists batch records to `speed_observations`, updates run status to `'completed'`, and returns execution summary statistics.
- `get_speed_observations(run_id, track_id=None, limit=None, config=None, repository_root=None, connection=None)`: Queries stored speed observations and aggregate summary metrics for a speed run or vehicle track.

### Repository Operations (`backend.database.repository`)
- `insert_speed_observations(connection, rows)`: Batch inserts records into `speed_observations`.
- `fetch_speed_observations_for_run(connection, run_id, track_id=None)`: Fetches speed observations for a run, optionally filtered by vehicle track ID.
- `fetch_speed_observation_stats(connection, run_id)`: Aggregates counts (total, valid, unavailable, invalid) and computes mean/max speeds in km/h and m/s.
- `update_tracks_world_coordinates(connection, updates)`: Batch updates `tracks` table with `world_x`, `world_y`, and `calibration_id`.

### CLI Commands (`backend.cli`)
- `traffic-vision estimate-speed PARENT_RUN_ID [--calibration-id CALIBRATION_ID] [--config CONFIG]`: Executes calibrated speed estimation for a tracking parent run.
- `traffic-vision show-speed SPEED_RUN_ID [--track-id TRACK_ID] [--limit LIMIT] [--config CONFIG]`: Inspects persisted speed observations and statistics.

---

## 2. Changed and Created Files

| File | Status | Description |
|---|---|---|
| `prompts/phase_08_speed_estimation.md` | Modified | Audited and revised in place with exact schema tables/columns, config keys, interfaces, and test plan TP8-01..14. |
| `docs/data_dictionary.md` | Modified | Added canonical entity specification for `speed_observations`. |
| `configs/default.yaml` | Modified | Added `speed` configuration block with default parameters. |
| `backend/config.py` | Modified | Added default speed configuration and schema validation in `_validate()`. |
| `backend/speed.py` | Created | Pure calibrated speed estimation math, position smoothing, unit conversions, and quality flagging. |
| `backend/services/speed.py` | Created | Service orchestrating speed estimation runs, provenance recording, calibration verification, and query APIs. |
| `backend/database/repository.py` | Modified | Added repository CRUD and aggregate query functions for `speed_observations` and track world coordinates. |
| `backend/cli.py` | Modified | Added `estimate-speed` and `show-speed` CLI subcommands and execution branches. |
| `tests/test_speed.py` | Created | Unit tests for pure speed logic, unit conversions, constant velocity, timestamp gaps, jitter filtering, outlier cutoff, and config validation. |
| `tests/test_speed_service.py` | Created | Integration tests for database persistence, calibration invariants, target resolution, and CLI commands. |
| `docs/handoffs/phase_08/HANDOFF.md` | Created | This handoff document. |

---

## 3. Schema Usage and Invariants

No schema changes were required. The canonical table `speed_observations` in `backend/database/schema.sql` was used strictly as designed:
- **`speed_observations`**:
  - `speed_observation_id`: Primary key UUID.
  - `run_id`: References `processing_runs(run_id)`.
  - `video_id`: References `videos(video_id)`.
  - `track_id`: Integer vehicle track identifier.
  - `timestamp_s`: Authoritative media timestamp in seconds from source video timeline.
  - `speed_mps`: Speed in metres per second, or `NULL` when status is not `'valid'`.
  - `speed_kmh`: Speed in kilometres per hour ($= \text{speed\_mps} \times 3.6$), or `NULL` when status is not `'valid'`.
  - `calibration_id`: Foreign key referencing accepted `calibration_runs(calibration_id)`.
  - `status`: Observation status, strictly constrained by CHECK constraint `CHECK (status IN ('valid', 'invalid', 'unavailable'))`.
  - `smoothing_window`: Duration in seconds of temporal smoothing window.
  - `ground_point_method`: Projection contact point method, default `'bottom_center'`.

---

## 4. Configuration Schema and Defaults

In `configs/default.yaml`:
```yaml
speed:
  smoothing_method: moving_average
  smoothing_window_s: 0.5
  min_track_points: 3
  max_gap_seconds: 1.0
  min_displacement_m: 0.1
  max_plausible_speed_mps: 45.0
  ground_point_method: bottom_center
```

Validated in `backend/config.py`:
- `smoothing_method`: string, must be `'moving_average'` or `'none'`.
- `smoothing_window_s`: float/int $\ge 0.0$.
- `min_track_points`: integer $\ge 2$.
- `max_gap_seconds`: float/int $> 0.0$.
- `min_displacement_m`: float/int $\ge 0.0$.
- `max_plausible_speed_mps`: float/int $> 0.0$ (~162 km/h).
- `ground_point_method`: string, must be `'bottom_center'`.

---

## 5. Raw Test Results

Running `uv run pytest -q`:

```text
........................................................................ [ 52%]
..................................................................       [100%]
138 passed in 20.77s
```

Running `uv run pytest tests/test_speed.py tests/test_speed_service.py -v`:

```text
============================= test session starts =============================
platform win32 -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0 -- D:\Work\Personal\traffic-vision-final-year-project\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: D:\Work\Personal\traffic-vision-final-year-project
configfile: pyproject.toml
plugins: anyio-4.15.1
collecting ... collected 18 items

tests/test_speed.py::test_tp8_01_unit_conversions PASSED                 [  5%]
tests/test_speed.py::test_tp8_02_constant_velocity_matches_ground_truth PASSED [ 11%]
tests/test_speed.py::test_tp8_03_authoritative_timestamps_vs_nominal_fps PASSED [ 16%]
tests/test_speed.py::test_tp8_04_initial_point_status_unavailable PASSED [ 22%]
tests/test_speed.py::test_tp8_05_timestamp_gap_rule PASSED               [ 27%]
tests/test_speed.py::test_tp8_06_non_monotonic_and_zero_dt_marked_invalid PASSED [ 33%]
tests/test_speed.py::test_tp8_07_short_tracks_marked_unavailable PASSED  [ 38%]
tests/test_speed.py::test_tp8_08_stationary_vehicle_and_jitter_filtering PASSED [ 44%]
tests/test_speed.py::test_tp8_09_implausible_speed_outlier_rejection PASSED [ 50%]
tests/test_speed.py::test_tp8_10_deterministic_position_smoothing PASSED [ 55%]
tests/test_speed.py::test_uncalibrated_point_projection_failure_marked_invalid PASSED [ 61%]
tests/test_speed.py::test_invalid_trajectory_status_marked_invalid PASSED [ 66%]
tests/test_speed.py::test_tp8_14_config_validation_enforces_constraints PASSED [ 72%]
tests/test_speed_service.py::test_tp8_11_database_persistence_and_provenance PASSED [ 77%]
tests/test_speed_service.py::test_tp8_12_unaccepted_and_missing_calibration_rejected PASSED [ 83%]
tests/test_speed_service.py::test_auto_resolve_latest_accepted_calibration PASSED [ 88%]
tests/test_speed_service.py::test_missing_parent_run_rejected PASSED     [ 94%]
tests/test_speed_service.py::test_tp8_13_service_end_to_end_and_cli_commands PASSED [100%]

============================= 18 passed in 4.10s ==============================
```

All 120 prior tests plus 18 new Phase 08 tests passed (138 tests total).

---

## 6. Assumptions and Limitations

1. **Planar-Road Assumption**: Speed calculations assume the vehicle bottom-centre ground point moves on the flat ground plane calibrated in Phase 07. Road grade, elevation changes, or flyovers may introduce localized projective distortions.
2. **Ground Contact Point**: Speed estimation strictly depends on the bottom-centre contact point `(ground_x, ground_y)` of the vehicle bounding box. Bounding-box centres are prohibited.
3. **Observation Gaps**: Velocities are not interpolated across temporal observation gaps exceeding `max_gap_seconds` (default 1.0 s). Observations immediately following a gap are flagged with `status = 'unavailable'`.
4. **Initial Track Observation**: The initial observation point of any track ($i = 0$) has no preceding time interval and is explicitly marked with `status = 'unavailable'`. No measurement is fabricated.
5. **No Fabricated Data**: Software fixtures in the test suite are synthetic and explicitly labelled as such. Real-world validation against GPS or radar reference speeds will occur during field validation in Phase 12.

---

## 7. Dependencies for Phase 09 (Queue and Stopped Vehicles)

- Phase 09 consumes `speed_observations` (`speed_kmh`, `speed_mps`, `status`) to classify stopped vehicles against configurable stopped speed thresholds (e.g. $\le 5$ km/h for $\ge 3$ s).
- Phase 09 consumes calibrated world coordinates to measure queue lengths in metres (`queue_length_m`) within configured approach zones.

---

## 8. Independent Review Notice

In accordance with prompt instructions, this implementation model has run all phase tests and reported raw test results, but does not perform the final checks or declare the phase accepted. Final verification and review are reserved for independent review subagents.
