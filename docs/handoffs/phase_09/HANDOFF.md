# Phase 09 Handoff — Stopped Vehicle and Queue Detection

## 1. Delivered Interfaces and Modules

### Pure Queue Logic (`backend.queue`)
- `StopEvent`: Immutable dataclass representing a confirmed stopped episode for an individual vehicle track matching canonical `stop_events`: `stop_event_id`, `run_id`, `video_id`, `track_id`, `start_timestamp_s`, `end_timestamp_s`, `duration_s`, `threshold_kmh`, `status`. Includes `.to_dict()`.
- `QueueEvent`: Immutable dataclass representing a time-sliced queue observation matching canonical `queue_events`: `queue_event_id`, `run_id`, `video_id`, `zone_id`, `approach`, `timestamp_s`, `queue_length_m`, `queued_vehicle_count`, `status`. Includes `.to_dict()`.
- `point_in_polygon(x, y, polygon)`: Ray-casting containment test verifying whether vehicle road contact bottom-centre ground points `(ground_x, ground_y)` lie inside queue zones. Bounding-box centres are strictly rejected.
- `compute_queue_length_m(queued_points_world, stop_line_world=None)`: Physical Euclidean distance calculation in metres using ground-plane world coordinates:
  - When an approach stop line is associated, measures distance from the stop line reference to the furthest / rear-most queued vehicle in the zone.
  - When no stop line is configured, measures the maximum pairwise Euclidean distance between any pair of queued vehicles (queue span).
  - Returns `0.0` for sub-threshold counts and `None` for non-finite or invalid coordinates. Never falls back to pixel distance.
- `detect_stop_events_for_track(track_id, observations, stop_speed_threshold_kmh=5.0, min_stop_duration_s=3.0, max_gap_s=1.0, run_id="", video_id="")`: Evaluates speed observations for an individual track. Classifies speeds $\le \text{stop\_speed\_threshold\_kmh}$ as stopped; accumulates continuous duration; confirms episodes with duration $\ge \text{min\_stop\_duration\_s}$; breaks continuity on observation gaps $> \text{max\_gap\_s}$; flags non-monotonic or negative intervals ($\Delta t \le 0$) with `status = 'invalid'`.
- `detect_stop_events_for_tracks(track_observations, stop_speed_threshold_kmh=5.0, min_stop_duration_s=3.0, max_gap_s=1.0, run_id="", video_id="")`: Batch wrapper detecting stop events across multiple tracks.
- `detect_queue_events_at_timestamp(timestamp_s, stopped_tracks_at_t, zones, counting_lines, homography_matrix, min_queue_vehicles=2, stop_line_mapping=None, run_id="", video_id="")`: Evaluates queue state across all designated queue zones (`zone_type = 'queue'`) at a single sample instant. Identifies stopped vehicles inside each zone, counts them, decides queue formation ($\ge \text{min\_queue\_vehicles}$), and calculates calibrated queue length in metres. For uncalibrated input (`homography_matrix = None`), sets `queue_length_m = None` and `status = 'unavailable'`.
- `evaluate_queue_events_for_run(speed_observations, trajectories, zones, counting_lines, homography_matrix, config=None, run_id="", video_id="")`: Orchestrates run-wide evaluation by slicing the timeline at regular cadences governed by `aggregation_interval_s`, identifying active stopped vehicles and their ground contact positions, and evaluating queue events across all queue zones.

### Queue Detection Service (`backend.services.queue`)
- `run_queue_detection(parent_run_id, calibration_id=None, config=None, repository_root=None, connection=None)`: Orchestrates stopped vehicle and queue detection for a completed tracking or speed parent run. Validates calibration acceptance (`accepted = 1`), automatically resolves latest accepted calibration if omitted, records child `processing_runs` record with full provenance, computes stop events and queue observations, persists records to canonical `stop_events` and `queue_events` tables, updates run status to `'completed'`, and returns execution statistics.
- `get_queue_summary(run_id, config=None, repository_root=None, connection=None)`: Retrieves aggregate summary statistics for a queue detection run.
- `get_stop_events(run_id, track_id=None, limit=None, config=None, repository_root=None, connection=None)`: Queries persisted stop events with optional track and row-limit filters.
- `get_queue_events(run_id, zone_id=None, approach=None, limit=None, config=None, repository_root=None, connection=None)`: Queries persisted queue events with optional zone, approach, and row-limit filters.

### Repository Operations (`backend.database.repository`)
- `insert_stop_events(connection, rows)`: Batch inserts records into canonical `stop_events` table.
- `insert_queue_events(connection, rows)`: Batch inserts records into canonical `queue_events` table.
- `fetch_stop_events_for_run(connection, run_id, track_id=None)`: Fetches stop events for a run, optionally filtered by track ID.
- `fetch_queue_events_for_run(connection, run_id, zone_id=None, approach=None)`: Fetches queue events for a run, optionally filtered by zone ID or approach.
- `fetch_queue_detection_stats(connection, run_id)`: Aggregates summary statistics for stops (total, valid, mean/max duration) and queues (total, valid, formed, mean/max length, max queued vehicles).

### CLI Commands (`backend.cli`)
- `traffic-vision detect-queue PARENT_RUN_ID [--calibration-id CALIBRATION_ID] [--config CONFIG]`: Executes stopped vehicle and calibrated queue detection for a completed parent run.
- `traffic-vision show-queue RUN_ID [--zone-id ZONE_ID] [--approach APPROACH] [--limit LIMIT] [--config CONFIG]`: Inspects persisted queue events and observations.
- `traffic-vision show-stops RUN_ID [--track-id TRACK_ID] [--limit LIMIT] [--config CONFIG]`: Inspects persisted stopped vehicle events.

---

## 2. Changed and Created Files

| File | Status | Description |
|---|---|---|
| `prompts/phase_09_queue_detection.md` | Authority | Revised and executed as authority. |
| `docs/data_dictionary.md` | Pre-existing | Canonical entity definitions for `stop_events` and `queue_events`. |
| `configs/default.yaml` | Pre-existing | `queue` configuration section with default parameters. |
| `backend/config.py` | Pre-existing | Configuration schema validation for `queue` section in `_validate()`. |
| `backend/queue.py` | Created | Pure stopped vehicle detection logic, ray-casting point-in-polygon containment, queue formation, and calibrated metric length calculation. |
| `backend/services/queue.py` | Created | Service orchestrating queue detection runs, provenance recording, calibration validation, and query APIs. |
| `backend/database/repository.py` | Modified | Added additive repository CRUD and summary statistics functions for `stop_events` and `queue_events`. |
| `backend/cli.py` | Modified | Added additive `detect-queue`, `show-queue`, and `show-stops` CLI subparsers and execution branches. |
| `tests/test_queue.py` | Created | Focused unit tests for pure queue and stop logic covering TP9-01..11, TP9-14, TP9-16, containment, and edge cases. |
| `tests/test_queue_service.py` | Created | Service and CLI integration tests with synthetic fixtures covering TP9-12, TP9-13, TP9-15, and query filters. |
| `docs/handoffs/phase_09/HANDOFF.md` | Created | This handoff document. |

---

## 3. Schema Usage and Invariants

No schema changes were required. Canonical tables `stop_events` and `queue_events` in `backend/database/schema.sql` were used strictly as designed:
- **`stop_events`**:
  - `stop_event_id`: Primary key UUID.
  - `run_id`: References `processing_runs(run_id)`.
  - `video_id`: References `videos(video_id)`.
  - `track_id`: Integer vehicle track identifier.
  - `start_timestamp_s`: Authoritative media timestamp when stopped state began.
  - `end_timestamp_s`: Authoritative media timestamp when stopped state ended.
  - `duration_s`: Total stopped duration in seconds (`end_timestamp_s - start_timestamp_s`).
  - `threshold_kmh`: Speed threshold in km/h used to classify stopped state.
  - `status`: Observation status, strictly constrained by CHECK constraint `CHECK (status IN ('valid', 'invalid', 'unavailable'))`.
- **`queue_events`**:
  - `queue_event_id`: Primary key UUID.
  - `run_id`: References `processing_runs(run_id)`.
  - `video_id`: References `videos(video_id)`.
  - `zone_id`: Identifier of queue zone referencing `zones(zone_id)`.
  - `approach`: Declared intersection approach name.
  - `timestamp_s`: Authoritative media timestamp from source timeline for evaluation instant.
  - `queue_length_m`: Calibrated physical queue length in metres; `NULL` when uncalibrated or invalid.
  - `queued_vehicle_count`: Integer count of stopped vehicles forming queue in zone.
  - `status`: Observation status, strictly constrained by CHECK constraint `CHECK (status IN ('valid', 'invalid', 'unavailable'))`.

---

## 4. Configuration Schema and Defaults

In `configs/default.yaml`:
```yaml
queue:
  stop_speed_threshold_kmh: 5.0
  min_stop_duration_s: 3.0
  min_queue_vehicles: 2
  aggregation_interval_s: 1.0
  max_gap_seconds: 1.0
  stop_line_mapping: {}
```

Validated in `backend/config.py`:
- `stop_speed_threshold_kmh`: float/int $> 0.0$ (default 5.0 km/h).
- `min_stop_duration_s`: float/int $\ge 0.0$ (default 3.0 s).
- `min_queue_vehicles`: integer $\ge 1$ (default 2).
- `aggregation_interval_s`: float/int $> 0.0$ (default 1.0 s).
- `max_gap_seconds`: float/int $> 0.0$ (default 1.0 s).
- `stop_line_mapping`: mapping of `zone_id` to `line_id` (default `{}`).

---

## 5. Raw Test Results

Running `uv run pytest -q`:

```text
........................................................................ [ 45%]
........................................................................ [ 91%]
..............                                                           [100%]
158 passed in 22.98s
```

Running `uv run pytest tests/test_queue.py tests/test_queue_service.py -v`:

```text
============================= test session starts =============================
platform win32 -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0 -- D:\Work\Personal\traffic-vision-final-year-project\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: D:\Work\Personal\traffic-vision-final-year-project
configfile: pyproject.toml
plugins: anyio-4.15.1
collecting ... collected 20 items

tests/test_queue.py::test_tp9_01_speed_threshold_boundary PASSED         [  5%]
tests/test_queue.py::test_tp9_02_duration_accumulation PASSED            [ 10%]
tests/test_queue.py::test_tp9_03_temporal_gap_rule PASSED                [ 15%]
tests/test_queue.py::test_tp9_04_non_monotonic_and_negative_dt_invalid PASSED [ 20%]
tests/test_queue.py::test_tp9_05_min_queue_vehicles_boundary PASSED      [ 25%]
tests/test_queue.py::test_tp9_06_queue_formation_trigger PASSED          [ 30%]
tests/test_queue.py::test_tp9_07_queue_zone_spatial_containment PASSED   [ 35%]
tests/test_queue.py::test_tp9_08_calibrated_world_coordinate_queue_length PASSED [ 40%]
tests/test_queue.py::test_tp9_09_uncalibrated_input_and_no_pixel_fallback PASSED [ 45%]
tests/test_queue.py::test_tp9_10_stop_line_distance_and_ordering PASSED  [ 50%]
tests/test_queue.py::test_tp9_11_aggregation_interval_time_slicing PASSED [ 55%]
tests/test_queue.py::test_tp9_14_config_validation_enforces_queue_parameters PASSED [ 60%]
tests/test_queue.py::test_tp9_16_signal_phase_independence PASSED        [ 65%]
tests/test_queue.py::test_point_in_polygon_ray_casting PASSED            [ 70%]
tests/test_queue.py::test_compute_queue_length_m_edge_cases PASSED       [ 75%]
tests/test_queue_service.py::test_tp9_12_database_persistence_and_provenance PASSED [ 80%]
tests/test_queue_service.py::test_tp9_13_unaccepted_calibration_rejection PASSED [ 85%]
tests/test_queue_service.py::test_missing_or_incomplete_parent_run PASSED [ 90%]
tests/test_queue_service.py::test_tp9_15_cli_commands_end_to_end PASSED  [ 95%]
tests/test_queue_service.py::test_get_queue_summary_and_query_filters PASSED [100%]

============================= 20 passed in 2.37s ==============================
```

All 138 existing tests plus 20 new Phase 09 tests passed (158 tests total).

---

## 6. Assumptions and Limitations

1. **Signal-Phase Independence**: Traffic Vision operates as an offline CV and data-collection system without external signal controller telemetry. Queue detection relies exclusively on computer-vision speed observations and spatial queue zone geometry.
2. **Bottom-Centre Ground Point**: Queue zone containment strictly tests the bottom-centre ground contact point `(ground_x, ground_y)` of the vehicle bounding box. Bounding-box centres are strictly prohibited.
3. **No Pixel Distance Fallback**: When calibration is unaccepted, missing, or projection fails, queue length is recorded as `NULL` with `status = 'unavailable'` or `'invalid'`. Pixel distance is never computed or substituted.
4. **No Final Congestion Index**: In strict accordance with prompt boundary instructions, no final congestion index, score, or emission model was computed.
5. **No Fabricated Data**: Software fixtures in the test suite are synthetic and explicitly labelled as software fixtures.

---

## 7. Dependencies for Phase 10

- Phase 10 (Export, Analytics, or Reporting) consumes `stop_events` and `queue_events` records for aggregate corridor metrics, delay analysis, and CSV/JSON reporting.
- Provenance chain links derived queue runs through `parent_run_id` to speed estimation runs and ByteTrack tracking runs.

---

## 8. Independent Review Notice

In accordance with prompt instructions, this implementation model has run all phase tests and reported raw test results, but does not perform the final checks or declare the phase accepted. Final verification and review are reserved for independent review subagents.
