# Phase 06 — Vehicle Counting, Movement, and Ground Truth

## Objective
Implement only crossing events, movement derivation, 15-minute traffic bins, vehicles/hour, and the initial counting ground-truth set. This prompt is independently executable after the stated dependencies are complete.

## Master sections implemented
crossing events, movement derivation, 15-minute traffic bins, vehicles/hour, and the initial counting ground-truth set

## Boundary
Implement nothing except this phase. Do not silently implement later-phase functionality.
Use `backend/database/schema.sql` and `docs/data_dictionary.md` as the canonical data contract.
Every derived/result row must retain `run_id` and relevant source video/frame/timestamp provenance.

## Scope
- Detect counting-line crossings using Phase 04 `build_trajectories()` ground points (never raw `tracks.trajectory_status`) and the Phase 05 `point_side_of_line` / `side_of_line` helper.
- A crossing is defined by a sign change of the line side between consecutive observed ground points whose trajectory segment actually intersects the counting-line segment (`segments_intersect`).
- Honour `direction_vector` for unidirectional counting lines; crossings opposing the line direction vector are not counted. Bidirectional lines count valid crossings in both directions.
- Prevent duplicate counting per `(track_id, line_id)` using configurable `min_reentry_gap_s` (default 2.0 s). Preserve all raw crossing events in `crossing_events` with the `deduplicated` flag recorded; nothing is silently dropped.
- Do not interpolate or infer crossings across temporal gaps larger than the Phase 04 trajectory gap rule (`max_gap_seconds`, default 1.0 s).
- Derive movement (`left`, `through`, `right`, `u_turn`, `unknown`) from the track's entry zone and exit zone approaches (Phase 05 polygonal zones) using a configurable `approach_pair -> movement` mapping in configuration. Any unresolved movement is classified as `'unknown'`, never guessed.
- Aggregate traffic volume into 15-minute bins (default 900 s) keyed by video `timestamp_s`, broken down by `vehicle_class`, `approach`, and `movement`.
- Always retain `observed_duration_s` for each bin. Truncated or partial final bins record their actual observed duration.
- Extrapolate hourly rate as `extrapolated_vehicles_per_hour = count * 3600 / observed_duration_s`; when `observed_duration_s == 0`, extrapolated volume must be `NULL`.
- Introduce the canonical `video_segments` table (`segment_id` PK, `video_id` FK, `start_s`, `end_s`, `start_frame`, `end_frame`, `label`, `condition_notes`) and make `ground_truth_counts.video_segment_id` an enforced foreign key referencing it.
- Support loading ground-truth counting datasets from YAML/JSON files via CLI `traffic-vision load-ground-truth` (persisting into `ground_truth_sets`, `video_segments`, and `ground_truth_counts`).
- Execute vehicle counting for a tracking parent run via CLI `traffic-vision count RUN_ID`.
- Compare counted results against ground-truth counts via CLI `traffic-vision compare-counts RUN_ID`, reporting counted vs observed and absolute/percentage errors per approach/movement/class.
- Predefined tolerance config key `counting.error_tolerance_pct` (default 10%) is recorded in the comparison report, but `compare-counts` must NOT state that the counter passed or was accepted.
- No real ground-truth data is fabricated; synthetic fixtures are explicitly labelled as software test fixtures.

## Inputs and dependencies
- Phase 01: database connection, schema bootstrap/migration mechanism, `videos` records, authoritative `video_frames` PTS timestamps.
- Phase 03: track observations in `tracks` table.
- Phase 04: `backend.trajectories.build_trajectories()`, `TrajectoryPoint`, consensus class, and temporal gap configuration.
- Phase 05: counting-line configurations (`counting_lines`), zones (`zones`), `point_side_of_line`, `validate_counting_line`, `validate_zone`, and `segments_intersect` in `backend.geometry`.

## Database schema changes and migrations
Update `backend/database/schema.sql` and provide an explicit migration mechanism in `backend/database/connection.py`:
1. Add `video_segments` table:
   ```sql
   CREATE TABLE IF NOT EXISTS video_segments (
       segment_id TEXT PRIMARY KEY,
       video_id TEXT NOT NULL REFERENCES videos(video_id),
       start_s REAL NOT NULL,
       end_s REAL NOT NULL,
       start_frame INTEGER NOT NULL,
       end_frame INTEGER NOT NULL,
       label TEXT,
       condition_notes TEXT
   );
   ```
2. Update `ground_truth_counts` table to enforce foreign key `video_segment_id TEXT NOT NULL REFERENCES video_segments(segment_id)`.
3. Add `deduplicated INTEGER NOT NULL DEFAULT 0` column to `crossing_events`.
4. Add `observed_duration_s REAL` column to `traffic_volume_bins`.
5. Implement `migrate_database(database_path)` to upgrade existing Phase 05 SQLite databases by applying missing tables/columns and appending the new schema version hash into `schema_migrations`.
6. Existing tests and invariants must keep passing.

## Configuration
Add a `counting` section to `configs/default.yaml` and validate it in `backend/config.py`:
```yaml
counting:
  bin_duration_s: 900.0
  min_reentry_gap_s: 2.0
  error_tolerance_pct: 10.0
  movement_mapping:
    north:
      south: through
      east: left
      west: right
      north: u_turn
    south:
      north: through
      west: left
      east: right
      south: u_turn
    east:
      west: through
      north: right
      south: left
      east: u_turn
    west:
      east: through
      south: right
      north: left
      west: u_turn
```
- `bin_duration_s`: positive float/int, duration of traffic volume bins in seconds (default 900.0).
- `min_reentry_gap_s`: non-negative float/int, minimum time window between counted crossings for the same `(track_id, line_id)` (default 2.0).
- `error_tolerance_pct`: positive float/int, reference error tolerance percentage recorded in evaluation reports (default 10.0).
- `movement_mapping`: mapping from entry approach to exit approach to movement string.

## Data and metadata
Use canonical field names from `docs/data_dictionary.md`:
- `crossing_events`: `crossing_event_id`, `run_id`, `video_id`, `line_id`, `track_id`, `frame_number`, `timestamp_s`, `vehicle_class`, `direction`, `approach`, `movement`, `line_config_version`, `deduplicated`.
- `traffic_volume_bins`: `bin_id`, `run_id`, `video_id`, `line_id`, `bin_start_s`, `bin_duration_s`, `observed_duration_s`, `vehicle_class`, `approach`, `movement`, `count`, `extrapolated_vehicles_per_hour`.
- `video_segments`: `segment_id`, `video_id`, `start_s`, `end_s`, `start_frame`, `end_frame`, `label`, `condition_notes`.
- `ground_truth_sets`: `ground_truth_set_id`, `name`, `source_description`, `split_group`, `created_at`.
- `ground_truth_counts`: `ground_truth_count_id`, `ground_truth_set_id`, `video_segment_id`, `approach`, `movement`, `vehicle_class`, `observed_count`.

## Interface contract
- Pure counting logic in `backend/counting.py`:
  - `point_in_polygon(point, vertices) -> bool`
  - `derive_movement(track, zones, movement_mapping) -> str`
  - `detect_crossings_for_trajectory(trajectory, counting_lines, min_reentry_gap_s, max_gap_seconds) -> list[dict]`
  - `aggregate_volume_bins(crossings, bin_duration_s, video_duration_s) -> list[dict]`
  - `calculate_counting_comparison(counted_rows, ground_truth_counts, tolerance_pct) -> dict`
- Counting orchestration service in `backend/services/counting.py`:
  - `run_counting(parent_run_id, config, repository_root) -> str`
  - `load_ground_truth(file_path, config, repository_root, connection) -> dict`
  - `compare_counts(run_id, ground_truth_set_id, config, repository_root, connection) -> dict`
- Database migration in `backend/database/connection.py`:
  - `migrate_database(database_path) -> str`
- CLI commands in `backend/cli.py`:
  - `traffic-vision count RUN_ID [--config CONFIG]`
  - `traffic-vision load-ground-truth FILE [--config CONFIG]`
  - `traffic-vision compare-counts RUN_ID [--ground-truth-set SET_ID] [--config CONFIG]`
  - `traffic-vision migrate-db [--config CONFIG]`

## Error handling
Reject or explicitly mark invalid inputs and failed processing:
- Reject non-existent parent runs or incomplete tracking runs.
- Reject undeclared or malformed ground-truth datasets with missing foreign keys.
- Preserve all detected crossing events; duplicate re-entries are flagged `deduplicated = 1`, never dropped.
- Unknown movements are stored as `'unknown'`, never guessed or interpolated.
- Do not invent measurements or fabricate ground truth.

## Tests and evidence
Add focused tests in `tests/test_counting.py` and `tests/test_counting_service.py`. All tests must pass, and raw test results must be recorded in the phase handoff. Test fixtures must be labelled as software fixtures.

## Handoff
Create `docs/handoffs/phase_06/HANDOFF.md` containing changed files, interfaces, schema changes, config keys/defaults, input/output contracts, raw test results, assumptions, limitations, unresolved issues, and dependencies for Phase 07.

## Completion criteria (measurable test plan TP6-01..TP6-12)
- **TP6-01**: No double counting — duplicate re-crossings within `min_reentry_gap_s` are flagged `deduplicated = 1` and excluded from volume bins.
- **TP6-02**: Bidirectional lines count valid crossings in both directions.
- **TP6-03**: Unidirectional lines honour `direction_vector`; crossings opposing the direction vector are not counted.
- **TP6-04**: Movement derivation resolves `left`, `through`, `right`, `u_turn` from entry/exit zones; unresolved movements default to `'unknown'` without guessing.
- **TP6-05**: 15-minute bin boundaries are aligned with video timestamps (`bin_start_s = k * 900`).
- **TP6-06**: Partial final bin keeps actual `observed_duration_s`.
- **TP6-07**: Extrapolated vehicles/hour is computed as `count * 3600 / observed_duration_s`.
- **TP6-08**: Zero-duration bins extrapolate to `NULL` (None).
- **TP6-09**: Raw events preserved in `crossing_events` with `deduplicated` flag; nothing silently dropped.
- **TP6-10**: Foreign key integrity strictly enforced for `video_segments`, `ground_truth_counts`, and `crossing_events`.
- **TP6-11**: Schema upgrade successfully migrates an existing Phase 05 database to Phase 06 schema.
- **TP6-12**: Ground-truth comparison calculates counted vs observed and absolute/percent errors, records `error_tolerance_pct`, and does NOT state that the counter passed or was accepted.

## Explicit exclusions
Calibration, homography, speed observations, queue metrics, manual review, active learning, model training, dashboard, SUMO.

## Independent review
Do not perform the final checks or acceptance review in this task. Prompt checking, implementation review, testing review, and completion verification will be performed separately by Pro subagents that are different from the normal implementation model.
Run your own phase tests and report raw output, but do not declare the phase accepted.