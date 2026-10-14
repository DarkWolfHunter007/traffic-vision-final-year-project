# Phase 08 — Speed Estimation

## Objective
Implement only calibrated world-coordinate speed estimation using authoritative timestamps. This prompt is independently executable after the stated dependencies are complete.

## Master sections implemented
Speed, Time and video handling, Ground point and geometry, Provenance (Sections 5, 6, 9, 13, 19)

## Boundary
Implement nothing except this phase. Do not silently implement later-phase functionality.
Use `backend/database/schema.sql` and `docs/data_dictionary.md` as the canonical data contract.
Every derived/result row must retain `run_id` and relevant source video/frame/timestamp provenance.

## Scope
- Transform bottom-centre trajectory ground points (`ground_x`, `ground_y`) to road-plane world coordinates $(X, Y)$ in metres using an accepted Phase 07 planar homography calibration matrix $H$.
- Strictly reject vehicle bounding-box centres; enforce `ground_point_method = 'bottom_center'`.
- Calculate Euclidean distance in metres $\Delta d = \sqrt{(X_i - X_{i-1})^2 + (Y_i - Y_{i-1})^2}$ over authoritative elapsed decoder media time $\Delta t = t_i - t_{i-1}$ from `timestamp_s`. Never reconstruct or fall back to nominal FPS or `frame_number / FPS`.
- Compute instantaneous velocity in metres per second (m/s) and convert to kilometres per hour (km/h) via `speed_kmh = speed_mps * 3.6`.
- Apply deterministic temporal position smoothing (centered moving average of world coordinates over `smoothing_window_s` seconds) without bridging across observation gaps $> \text{max\_gap\_seconds}$.
- Outlier and quality flagging:
  - Mark initial track observation ($i = 0$) as `status = 'unavailable'` (no preceding time interval $\Delta t$).
  - Mark observations with elapsed time $\Delta t \le 0$ as `status = 'invalid'` (non-monotonic or zero timestamp).
  - Mark observations separated by gaps $\Delta t > \text{max_gap_seconds}$ as `status = 'unavailable'`.
  - Flag low-length tracks ($< \text{min_track_points}$) as `status = 'unavailable'`.
  - Flag low-displacement/stationary motion below `min_displacement_m` as valid speed 0.0 m/s (filtering sensor/pixel jitter for stopped vehicles).
  - Flag implausible speeds exceeding `max_plausible_speed_mps` as `status = 'invalid'`.
  - Flag uncalibrated points (e.g. projecting to infinity $w \approx 0$ or non-finite) or tracks with `trajectory_status == 'invalid'` as `status = 'invalid'`.
  - When status is `'unavailable'` or `'invalid'`, store `speed_mps = NULL` and `speed_kmh = NULL`; never fabricate values or substitute 0 for missing measurements.
- Persist observations to `speed_observations` with exact calibration provenance (`calibration_id`), `run_id`, `video_id`, `track_id`, `timestamp_s`, `smoothing_window`, and `ground_point_method`.

## Inputs and dependencies
- Phase 01: database connection, schema bootstrap, `videos`, `processing_runs`, provenance tracking.
- Phase 04: ordered trajectory histories, bottom-centre ground contact point convention (`ground_x`, `ground_y`), `build_trajectories()`.
- Phase 07: accepted camera calibration (`calibration_runs.accepted = 1`), homography projection functions `project_image_to_world()` in `backend.calibration`.

## Database schema and persistence
Prefer no schema change: canonical table `speed_observations` already exists in `backend/database/schema.sql`:
1. `speed_observations`:
   - `speed_observation_id`: TEXT PRIMARY KEY
   - `run_id`: TEXT NOT NULL REFERENCES processing_runs(run_id)
   - `video_id`: TEXT NOT NULL REFERENCES videos(video_id)
   - `track_id`: INTEGER NOT NULL
   - `timestamp_s`: REAL NOT NULL
   - `speed_mps`: REAL (NULL when status != 'valid')
   - `speed_kmh`: REAL (NULL when status != 'valid')
   - `calibration_id`: TEXT NOT NULL REFERENCES calibration_runs(calibration_id)
   - `status`: TEXT NOT NULL CHECK (status IN ('valid', 'invalid', 'unavailable'))
   - `smoothing_window`: REAL
   - `ground_point_method`: TEXT NOT NULL DEFAULT 'bottom_center'
2. `tracks` table invariant:
   - `world_x`, `world_y` remain NULL unless an accepted calibration run is referenced via `calibration_id`.

## Configuration
Add a `speed` section to `configs/default.yaml` and validate it in `backend/config.py`:
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
- `smoothing_method`: string, must be `'moving_average'` or `'none'`.
- `smoothing_window_s`: float/int $\ge 0.0$, duration of temporal smoothing window in seconds (default 0.5).
- `min_track_points`: integer $\ge 2$, minimum number of observations required for valid speed (default 3).
- `max_gap_seconds`: float/int $> 0.0$, maximum time gap between consecutive observations before breaking continuity (default 1.0).
- `min_displacement_m`: float/int $\ge 0.0$, minimum displacement threshold below which vehicle is stationary (default 0.1).
- `max_plausible_speed_mps`: float/int $> 0.0$, upper physical speed threshold for outlier rejection (default 45.0 m/s $\approx$ 162 km/h).
- `ground_point_method`: string, must be `'bottom_center'`.

## Data and metadata
Use canonical field names from `backend/database/schema.sql` and `docs/data_dictionary.md`.
Preserve source video identity, source SHA-256, processing run, model/configuration provenance, and authoritative timestamps where applicable.
Never fall back to nominal FPS when authoritative timestamps are available.
Never fabricate research data (no invented calibration points, ground truth, or measurements; use clearly-labelled software fixtures in tests only).

## Interface contract
- Pure logic module in `backend/speed.py`:
  - `mps_to_kmh(speed_mps: float) -> float`
  - `kmh_to_mps(speed_kmh: float) -> float`
  - `smooth_trajectory_positions(points: Sequence[tuple[float, float, float]], window_s: float, max_gap_s: float) -> list[tuple[float, float]]`
  - `estimate_speeds_for_trajectory(trajectory, homography_matrix, calibration_id, run_id, config=None) -> list[SpeedObservation]`
  - `estimate_speeds_for_trajectories(trajectories, homography_matrix, calibration_id, run_id, config=None) -> dict[int, list[SpeedObservation]]`
- Speed estimation service in `backend/services/speed.py`:
  - `run_speed_estimation(parent_run_id, calibration_id=None, config=None, repository_root=None, connection=None) -> dict[str, Any]`
  - `get_speed_observations(run_id, track_id=None, limit=None, config=None, repository_root=None, connection=None) -> dict[str, Any]`
- Repository operations in `backend/database/repository.py`:
  - `insert_speed_observations(connection, rows)`
  - `fetch_speed_observations_for_run(connection, run_id, track_id=None)`
  - `fetch_speed_observation_stats(connection, run_id)`
- CLI commands in `backend/cli.py`:
  - `traffic-vision estimate-speed PARENT_RUN_ID [--calibration-id CALIBRATION_ID] [--config CONFIG]`
  - `traffic-vision show-speed SPEED_RUN_ID [--track-id TRACK_ID] [--limit LIMIT] [--config CONFIG]`

## Error handling
Reject or explicitly mark invalid inputs and failed processing:
- Reject non-existent parent runs or uncompleted parent tracking runs.
- Reject non-existent or unaccepted calibration runs (`accepted = 0`).
- If no calibration ID is supplied, automatically resolve the latest accepted calibration for the video; raise error if none exists.
- Reject division by zero or non-monotonic timestamps ($\Delta t \le 0$) with `status = 'invalid'`.
- Do not bridge gaps $> \text{max_gap_seconds}$; mark post-gap observation as `status = 'unavailable'`.
- Do not invent measurements or replace unavailable research values with zero.

## Tests and evidence
Add focused tests in `tests/test_speed.py` and `tests/test_speed_service.py`.
All existing tests and new phase tests must pass (`uv run pytest -q`).
Report raw pytest output in the handoff.
Test fixtures may be synthetic but must be clearly labelled as software fixtures.

## Handoff
Create `docs/handoffs/phase_08/HANDOFF.md` containing changed files, interfaces, schema changes, config keys/defaults, input/output contracts, raw test results, assumptions, limitations, unresolved issues, and dependencies for Phase 09.

## Completion criteria (measurable test plan TP8-01..TP8-14)
- **TP8-01**: Unit conversions: `mps_to_kmh` and `kmh_to_mps` compute exact conversions ($1\text{ m/s} = 3.6\text{ km/h}$).
- **TP8-02**: Distance and constant velocity: Synthetic vehicle moving at known constant velocity (e.g. 10 m/s = 36 km/h) over regular timestamps yields exact speed.
- **TP8-03**: Authoritative timestamps: Speed calculation uses `timestamp_s` (PTS) and varies inversely with variable frame intervals (never nominal FPS).
- **TP8-04**: Initial observation handling: First point of a track ($i = 0$) has no prior interval and is recorded with `status = 'unavailable'`, `speed_mps = None`, `speed_kmh = None`.
- **TP8-05**: Timestamp gap rule: Consecutive observations separated by $\Delta t > \text{max_gap_seconds}$ are not bridged; post-gap observation is marked `status = 'unavailable'`.
- **TP8-06**: Non-monotonic / duplicate timestamps: $\Delta t \le 0$ is marked `status = 'invalid'`.
- **TP8-07**: Short tracks: Tracks with fewer than `min_track_points` are marked `status = 'unavailable'`.
- **TP8-08**: Stationary vehicle / jitter filtering: Displacements below `min_displacement_m` produce valid speed of 0.0 m/s (0.0 km/h).
- **TP8-09**: Outlier rejection: Speeds exceeding `max_plausible_speed_mps` are flagged as `status = 'invalid'`.
- **TP8-10**: Deterministic position smoothing: Smoothing window reduces high-frequency position jitter without shifting mean trajectory.
- **TP8-11**: Database persistence and provenance: Records in `speed_observations` retain `run_id`, `video_id`, `track_id`, `timestamp_s`, `calibration_id`, and `ground_point_method = 'bottom_center'`.
- **TP8-12**: Unaccepted calibration rejection: Speed estimation rejects unaccepted calibration runs (`accepted = 0`) or missing calibrations.
- **TP8-13**: End-to-end service and CLI: `traffic-vision estimate-speed` and `traffic-vision show-speed` CLI commands succeed and produce valid JSON output.
- **TP8-14**: Config validation: Config loader validates `speed` section keys and constraints.

## Explicit exclusions
Queue length / stopped vehicle classification (`queue_events`, `stop_events`), manual review, active learning, model training, emissions, MCE, SUMO.

## Independent review
Do not perform the final checks or acceptance review in this task. Prompt checking, implementation review, testing review, and completion verification will be performed separately by Pro subagents that are different from the normal implementation model.
Run your own phase tests and report raw output, but do not declare the phase accepted.