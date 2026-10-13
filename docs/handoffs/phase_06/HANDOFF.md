# Phase 06 Handoff — Vehicle Counting, Movement Derivation, and Ground Truth

## 1. Delivered Interfaces and Modules

### Pure Counting Logic (`backend.counting`)
- `point_in_polygon(point, vertices)`: Pure Ray-casting point-in-polygon containment test for planar polygons.
- `derive_movement(trajectory, zones, movement_mapping=None)`: Derives turning movement (`left`, `through`, `right`, `u_turn`, `unknown`) based on trajectory points passing through Phase 05 entry and exit zones, mapped via configurable `approach_pair -> movement` dictionary. Unresolved movements return `'unknown'` and are never guessed.
- `detect_crossings_for_trajectory(trajectory, counting_lines, min_reentry_gap_s=2.0, max_gap_seconds=1.0, movement="unknown", entry_approach=None)`: Detects line crossing events for a trajectory using Phase 04 `build_trajectories()` ground points (never raw `tracks.trajectory_status`) and Phase 05 `point_side_of_line` and `segments_intersect`. Preserves all raw crossing events with the `deduplicated` flag. Unidirectional lines honour `direction_vector` (opposing crossings marked `deduplicated = 1`). Re-entries within `min_reentry_gap_s` marked `deduplicated = 1`. Does not interpolate through gaps larger than `max_gap_seconds`.
- `aggregate_volume_bins(crossings, run_id, video_id, bin_duration_s=900.0, video_duration_s=None)`: Aggregates valid (`deduplicated == 0`) crossings into 15-minute (or configured) time bins keyed by video `timestamp_s`, broken down by `vehicle_class`, `approach`, and `movement`. Retains `observed_duration_s` for every bin (including partial final bins). Computes `extrapolated_vehicles_per_hour = count * 3600 / observed_duration_s` (or `None` when observed duration is 0).
- `calculate_counting_comparison(counted_events, ground_truth_counts, video_segments=None, error_tolerance_pct=10.0)`: Compares counted volume against manual reference counts, reporting absolute and percentage error per approach/movement/class. Records `error_tolerance_pct` without declaring pass/fail or counter acceptance.

### Counting Orchestration Service (`backend.services.counting`)
- `run_counting(parent_run_id, config, repository_root, connection=None)`: Orchestrates counting run derived from a completed tracking run. Creates a new immutable `processing_runs` record with `parent_run_id`, fetches tracks, reconstructs trajectories via Phase 04 `build_trajectories()`, detects crossings, derives movements, inserts rows into `crossing_events` and `traffic_volume_bins`, and marks the run as completed.
- `load_ground_truth(file_path, config=None, repository_root=None, connection=None)`: Loads and validates YAML/JSON ground-truth datasets, enforcing foreign keys to `videos` and `video_segments`, and persisting rows into `ground_truth_sets`, `video_segments`, and `ground_truth_counts`.
- `compare_counts(run_id, ground_truth_set_id=None, config=None, repository_root=None, connection=None)`: Evaluates counting run against ground-truth counts for a video, generating a detailed error comparison report.

### Schema Migration (`backend.database.connection`)
- `migrate_database(database_path)`: Explicitly migrates an existing SQLite database (such as a Phase 05 database) to the canonical Phase 06 schema: adds `video_segments` table, adds `deduplicated` to `crossing_events`, adds `observed_duration_s` to `traffic_volume_bins`, and updates `schema_migrations` with the current schema hash.

### Repository Operations (`backend.database.repository`)
- `insert_video_segment`, `insert_video_segments`, `fetch_video_segments_for_video`, `fetch_video_segment_by_id`.
- `insert_ground_truth_set`, `fetch_ground_truth_set_by_id`.
- `insert_ground_truth_counts`, `fetch_ground_truth_counts_for_set`.
- `insert_crossing_events`, `fetch_crossing_events_for_run`.
- `insert_traffic_volume_bins`, `fetch_traffic_volume_bins_for_run`.

### CLI Commands (`backend.cli`)
- `traffic-vision count RUN_ID [--config CONFIG]`: Runs counting for a tracking parent run.
- `traffic-vision load-ground-truth FILE [--config CONFIG]`: Loads a ground-truth dataset from YAML/JSON file.
- `traffic-vision compare-counts RUN_ID [--ground-truth-set SET_ID] [--config CONFIG]`: Reports counted vs observed counts and error metrics.
- `traffic-vision migrate-db [--config CONFIG]`: Explicitly upgrades the canonical database schema.

---

## 2. Changed and Created Files

| File | Status | Description |
|---|---|---|
| `prompts/phase_06_vehicle_counting.md` | Modified | Revised per Phase 06 decisions: unambiguous requirements, data contract, CLI interfaces, and TP6-01..12 completion criteria. |
| `backend/database/schema.sql` | Modified | Added `video_segments` table, updated `ground_truth_counts.video_segment_id` FK, added `deduplicated` to `crossing_events`, added `observed_duration_s` to `traffic_volume_bins`. |
| `backend/database/connection.py` | Modified | Added `migrate_database(database_path)` to upgrade existing databases to the latest schema version hash. |
| `backend/database/repository.py` | Modified | Added repository CRUD operations for `video_segments`, `ground_truth_sets`, `ground_truth_counts`, `crossing_events`, and `traffic_volume_bins`. |
| `docs/data_dictionary.md` | Modified | Added canonical entity specifications for `video_segments`, `ground_truth_counts`, `crossing_events.deduplicated`, and `traffic_volume_bins.observed_duration_s`. |
| `configs/default.yaml` | Modified | Added `counting` configuration section (`bin_duration_s`, `min_reentry_gap_s`, `error_tolerance_pct`, `movement_mapping`). |
| `backend/config.py` | Modified | Added `counting` default configuration and schema validation rules. |
| `backend/counting.py` | Created | Pure counting logic: line-crossing detection, deduplication, movement derivation, bin aggregation, and comparison computation. |
| `backend/services/counting.py` | Created | Service orchestration: running counting runs, loading ground-truth datasets, and computing comparisons. |
| `backend/cli.py` | Modified | Added `count`, `load-ground-truth`, `compare-counts`, and `migrate-db` CLI subparsers and execution branches. |
| `tests/test_counting.py` | Created | Focused unit tests for pure counting logic covering TP6-01..09, TP6-12, and gap rules. |
| `tests/test_counting_service.py` | Created | Integration tests covering TP6-10 (FK integrity), TP6-11 (Phase 05 DB schema migration), end-to-end service runs, and CLI commands. |
| `docs/handoffs/phase_06/HANDOFF.md` | Created | This handoff documentation. |

---

## 3. Schema Usage and Invariants

Canonical schema updates in `backend/database/schema.sql`:
- **`video_segments`**:
  - `segment_id`: Text primary key.
  - `video_id`: Foreign key referencing `videos(video_id)`.
  - `start_s`, `end_s`: Real seconds from video start timeline.
  - `start_frame`, `end_frame`: Frame number bounds.
  - `label`: Optional semantic label.
  - `condition_notes`: Optional condition description.
- **`ground_truth_counts`**:
  - `ground_truth_count_id`: Text primary key.
  - `ground_truth_set_id`: Foreign key referencing `ground_truth_sets(ground_truth_set_id)`.
  - `video_segment_id`: Enforced foreign key referencing `video_segments(segment_id)`.
  - `approach`: Declared approach name.
  - `movement`: Turning movement (`left`, `through`, `right`, `u_turn`, `unknown`).
  - `vehicle_class`: Vehicle class name.
  - `observed_count`: Integer reference count.
- **`crossing_events`**:
  - `deduplicated`: Integer flag (0 or 1). `0` for countable crossings; `1` for duplicate re-crossings within `min_reentry_gap_s` or opposing unidirectional lines. All raw events are preserved; nothing is silently dropped.
- **`traffic_volume_bins`**:
  - `observed_duration_s`: Actual elapsed observation duration in seconds for each bin. Truncated or partial final bins retain their actual duration.
  - `extrapolated_vehicles_per_hour`: Hourly extrapolated rate `count * 3600 / observed_duration_s`, or `NULL` when `observed_duration_s == 0`.

---

## 4. Configuration Schema and Defaults

In `configs/default.yaml`:
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

---

## 5. Raw Test Results

Running `uv run pytest -q`:

```text
........................................................................ [ 67%]
..................................                                       [100%]
106 passed in 9.91s
```

Running `uv run pytest tests/test_counting.py tests/test_counting_service.py -v`:

```text
============================= test session starts =============================
platform win32 -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0 -- D:\Work\Personal\traffic-vision-final-year-project\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: D:\Work\Personal\traffic-vision-final-year-project
configfile: pyproject.toml
plugins: anyio-4.15.1
collecting ... collected 16 items

tests/test_counting.py::test_tp6_01_no_double_counting_and_deduplication PASSED [  6%]
tests/test_counting.py::test_tp6_02_bidirectional_lines_count_both_directions PASSED [ 12%]
tests/test_counting.py::test_tp6_03_unidirectional_wrong_way_not_counted PASSED [ 18%]
tests/test_counting.py::test_tp6_04_movement_derivation_and_unknown PASSED [ 25%]
tests/test_counting.py::test_tp6_05_15_minute_bin_boundaries PASSED      [ 31%]
tests/test_counting.py::test_tp6_06_partial_final_bin_keeps_observed_duration PASSED [ 37%]
tests/test_counting.py::test_tp6_07_hourly_extrapolation_calculation PASSED [ 43%]
tests/test_counting.py::test_tp6_08_zero_duration_bin_extrapolates_to_null PASSED [ 50%]
tests/test_counting.py::test_tp6_09_raw_events_preserved_nothing_silently_dropped PASSED [ 56%]
tests/test_counting.py::test_tp6_gap_rule_prevents_interpolation_through_large_gaps PASSED [ 62%]
tests/test_counting.py::test_tp6_12_counting_comparison_and_no_acceptance_claim PASSED [ 68%]
tests/test_counting_service.py::test_tp6_10_foreign_key_integrity PASSED [ 75%]
tests/test_counting_service.py::test_tp6_11_schema_upgrade_from_phase_05_db PASSED [ 81%]
tests/test_counting_service.py::test_counting_service_end_to_end PASSED  [ 87%]
tests/test_counting_service.py::test_load_ground_truth_and_compare_counts PASSED [ 93%]
tests/test_counting_service.py::test_cli_counting_commands PASSED        [100%]

============================= 16 passed in 1.26s ==============================
```

All 90 prior tests plus 16 new Phase 06 tests passed (106 tests total).

---

## 6. Assumptions and Limitations

1. **Ground-Point Reliance**: Crossing detection strictly uses bottom-centre ground points from Phase 04 `build_trajectories()`. Tracker bounding box centres or raw `tracks.trajectory_status` are never used.
2. **Gap Rule**: Crossings are not interpolated across temporal observation gaps larger than `trajectories.max_gap_seconds` (default 1.0 s).
3. **Movement Derivation**: Movements are resolved strictly from entry and exit zone approach pairs. Trajectories that do not intersect both an entry zone and an exit zone evaluate to `'unknown'`; movement is never guessed.
4. **Acceptance Policy**: Ground-truth comparisons record error metrics and `counting.error_tolerance_pct` (default 10%), but do not state that the counter passed or was accepted. Final acceptance requires human researcher review.
5. **Software Test Fixtures**: All ground-truth clips and counts in the test suite are synthetic software test fixtures explicitly labelled as such.

---

## 7. Dependencies for Phase 07 (Camera Calibration)

- Phase 07 owns camera calibration, homography estimation, planar road verification, and reprojection error metrics.
- Phase 07 will populate `calibration_runs` and `calibration_points`.
- Calibrated world coordinates in metres (`world_x`, `world_y`) and physical speed observations (`speed_observations`) remain unavailable until Phase 07 is completed and accepted.

---

## 8. Independent Review Notice

In accordance with prompt instructions, this implementation model has run all phase tests and reported raw test results, but does not perform the final checks or declare the phase accepted. Final verification and review are reserved for independent review subagents.
