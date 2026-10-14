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
  - Applies symmetric centred moving-average position smoothing if `smoothing_method == 'moving_average'` and `smoothing_window_s > 0`; the half-width shrinks to the largest symmetric span inside one gap-free segment and within the window (never bridges gaps), so constant velocity gives the exact true speed for any track length and frame rate.
  - Flags initial track observation ($i = 0$) as `status = 'unavailable'` (no preceding time interval $\Delta t$).
  - Flags non-monotonic or zero timestamps ($\Delta t \le 0$) as `status = 'invalid'`.
  - Flags observation gaps ($\Delta t > \text{max_gap_seconds}$) as `status = 'unavailable'`.
  - Flags short tracks ($< \text{min_track_points}$) as `status = 'unavailable'`.
  - Stationary rule (frame-rate independent): speed over a reference span of at least `STATIONARY_REFERENCE_S = 0.5` s of track time (raw positions, clipped to the gap-free segment) below `min_displacement_m / 0.5` m/s gives valid 0.0 m/s / 0.0 km/h. Because the decision uses a time span rather than a single step, jitter at segment edges (where smoothing cannot be applied) also yields 0.0 at any fps. This holds for segments >= 0.5 s; shorter gap-free segments use the displacement rule instead: total displacement over the whole segment below `min_displacement_m` gives valid 0.0, otherwise the instantaneous speed is used, except that with fewer than `MIN_POINTS_SHORT_SEGMENT = 5` points and a step speed at or above the stationary threshold the step is `unavailable` with NULL speeds (jitter cannot be told from motion).
  - Flags implausible speeds (> `max_plausible_speed_mps`) as `status = 'invalid'`, checking both the smoothed step speed and the raw unsmoothed step speed; every output whose smoothing window contains a flagged raw step is invalid.
  - `smoothing_window` is stored NULL when smoothing is not applied (method `'none'` or window 0).
  - Observation values (`speed_mps`, `speed_kmh`) are rounded to 4 decimal places; aggregate stats are rounded to 2.
  - Sets `speed_mps = None` and `speed_kmh = None` whenever status is `'unavailable'` or `'invalid'`; never fabricates zero or default measurements for missing research values.
- `estimate_speeds_for_trajectories(trajectories, homography_matrix, calibration_id, run_id, config=None)`: Batch wrapper applying speed estimation across a collection of trajectories.

### Speed Estimation Service (`backend.services.speed`)
- `run_speed_estimation(parent_run_id, calibration_id=None, config=None, repository_root=None, connection=None)`: Orchestrates speed estimation for a completed tracking parent run. Requires the parent to be a completed tracking run (rows in `tracks`, or notes starting `Phase 03 ByteTrack`). Validates calibration acceptance (`calibration_runs.accepted = 1`) and that an explicit calibration's `video_id` equals the parent run's `video_id`; automatically resolves latest accepted calibration if `calibration_id` is omitted, creates a child `processing_runs` record with full provenance, reconstructs trajectories via Phase 04 `build_trajectories()`, calculates speeds, persists batch records to `speed_observations` inside a SAVEPOINT (completion status and stats are produced inside the savepoint before release, so any failure leaves zero speed rows and marks the run `'failed'`. Transaction note: on a caller-supplied connection the service commits the caller's pending transaction, on both success and failure; only the service's own inserts are rolled back, and unrelated pending work is committed rather than discarded), updates run status to `'completed'`, and returns execution summary statistics.
- `get_speed_observations(run_id, track_id=None, limit=None, config=None, repository_root=None, connection=None)`: Queries stored speed observations and aggregate summary metrics for a speed run or vehicle track.

### Repository Operations (`backend.database.repository`)
- `insert_speed_observations(connection, rows)`: Batch inserts records into `speed_observations`.
- `fetch_speed_observations_for_run(connection, run_id, track_id=None)`: Fetches speed observations for a run, optionally filtered by vehicle track ID.
- `fetch_speed_observation_stats(connection, run_id)`: Aggregates counts (total, valid, unavailable, invalid) and computes mean/max speeds in km/h and m/s.
- World coordinates are NOT persisted: `tracks.world_x/world_y/calibration_id` remain NULL (the previously added, unused `update_tracks_world_coordinates` helper was removed). Speed observations carry `calibration_id` only.

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
| `backend/database/repository.py` | Modified | Added repository insert/fetch/aggregate functions for `speed_observations`. |
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
  - `smoothing_window`: Duration in seconds of temporal smoothing window; NULL when smoothing not applied.
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
........................................................................ [ 23%]
........................................................................ [ 46%]
........................................................................ [ 69%]
........................................................................ [ 93%]
.....................                                                    [100%]
309 passed in 26.01s
```

Phase 08 tests: `tests/test_speed.py` and `tests/test_speed_service.py` (value-checking tests for D1-D9, N1, N2, N4, N5, plus parametrised ultra-short post-gap segment tests).

Ultra-short segment rule: for gap-free segments with span < 0.5 s, valid 0.0 is reported only if displacement < min_displacement_m AND (the step speed is < min_displacement_m/0.5 s OR the segment has >= 5 points, so oscillating jitter is observable). Otherwise, with displacement below the threshold but fewer than 5 points and step speed at/above the threshold, jitter and motion are indistinguishable and the step is 'unavailable' with NULL speeds, never a fabricated valid 0.0.

---

## 6. Assumptions and Limitations

- **Known limitation (judge finding D-A):** the 5-point exemption in the short-segment rule counts points only and does not check that the path oscillates. A gap-free segment of >= 5 points spanning < 0.5 s with < 0.1 m total displacement is reported as valid 0.0 even for real slow/medium motion at very high frame rates (e.g. 2 m/s at 120 fps with 5-7 points, 1 m/s at 60 fps with 5-6 points, 4 m/s at 240 fps). Not covered by tests; recommended fix before relying on > 60 fps footage: require net displacement much smaller than summed step lengths, else mark `unavailable`.

1. **Planar-Road Assumption**: Speed calculations assume the vehicle bottom-centre ground point moves on the flat ground plane calibrated in Phase 07. Road grade, elevation changes, or flyovers may introduce localized projective distortions.
2. **Ground Contact Point**: Speed estimation strictly depends on the bottom-centre contact point `(ground_x, ground_y)` of the vehicle bounding box. Bounding-box centres are prohibited.
3. **Observation Gaps**: Velocities are not interpolated across temporal observation gaps exceeding `max_gap_seconds` (default 1.0 s). Observations immediately following a gap are flagged with `status = 'unavailable'`.
4. **Initial Track Observation**: The initial observation point of any track ($i = 0$) has no preceding time interval and is explicitly marked with `status = 'unavailable'`. No measurement is fabricated.
5. **No Fabricated Data**: Software fixtures in the test suite are synthetic and explicitly labelled as such. Real-world validation against GPS or radar reference speeds will occur during field validation in Phase 12.

---

## 7. Dependencies for Phase 09 (Queue and Stopped Vehicles)

- Phase 09 consumes `speed_observations` (`speed_kmh`, `speed_mps`, `status`) to classify stopped vehicles against configurable stopped speed thresholds (e.g. $\le 5$ km/h for $\ge 3$ s).
- World coordinates are NOT persisted in `speed_observations`. For queue lengths in metres (`queue_length_m`) within approach zones, Phase 09 must project from the stored ground points using the calibration homography itself.

---

## 8. Independent Review Notice

In accordance with prompt instructions, this implementation model has run all phase tests and reported raw test results, but does not perform the final checks or declare the phase accepted. Final verification and review are reserved for independent review subagents.
