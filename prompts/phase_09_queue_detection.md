# Phase 09 - Stopped Vehicle and Queue Detection

## Objective
Implement only stopped/slow states and calibrated queue observations. This prompt is independently executable after the stated dependencies are complete.

## Master sections implemented
Stopped/slow states and calibrated queue observations, Time and video handling, Ground point and geometry, Approaches, zones, and movements, Calibration, Provenance, Error handling and scientific integrity, Out of scope, Phase gates (Sections 5, 6, 9, 10, 11, 14, 19, 21, 22).

## Boundary
Implement nothing except this phase. Do not silently implement later-phase functionality.
Use `backend/database/schema.sql` and `docs/data_dictionary.md` as the canonical data contract.
Every derived/result row must retain `run_id` and relevant source video/frame/timestamp provenance.

## Scope
- Signal-phase scope gate decision: Traffic Vision is an offline computer-vision and data-collection subsystem for CCTV footage. Signal controller telemetry is not available; stopped vehicle and queue detection operates independently of signal phase timing using computer-vision speed observations and spatial queue zones.
- Stopped vehicle detection:
  - Detect stopped/slow states for individual vehicle tracks where instantaneous speed $\le \text{stop\_speed\_threshold\_kmh}$ (default 5.0 km/h) over authoritative decoder media timestamps (`pts_s` / `timestamp_s`).
  - Accumulate continuous stopped duration; confirm a stopped event when duration $\ge \text{min\_stop\_duration\_s}$ (default 3.0 s).
  - Break stopped continuity when temporal observation gap exceeds `max_gap_seconds` (default 1.0 s) or speed exceeds `stop_speed_threshold_kmh`.
  - Persist confirmed stopped episodes to the canonical `stop_events` table with `stop_event_id`, `run_id`, `video_id`, `track_id`, `start_timestamp_s`, `end_timestamp_s`, `duration_s`, `threshold_kmh`, and `status`.
- Queue zone spatial association:
  - Associate vehicle positions with designated queue zones (`zone_type = 'queue'`) from the Phase 05 `zones` table.
  - Test vehicle road contact using configurable bottom-centre ground points (`ground_x`, `ground_y`) and ray-casting polygon containment (`point_in_polygon`). Bounding-box centres are strictly prohibited.
- Queue formation and length calculation:
  - At regular sample instants (controlled by `aggregation_interval_s`, default 1.0 s), identify all stopped vehicles currently located inside each queue zone.
  - Count stopped vehicles in the zone (`queued_vehicle_count`).
  - If `queued_vehicle_count >= min_queue_vehicles` (default 2), a queue is detected.
  - If `queued_vehicle_count < min_queue_vehicles`, no queue is formed; record `queued_vehicle_count`, set `queue_length_m = 0.0`, and set `status = 'valid'`.
  - For formed queues, calculate physical queue length in metres (`queue_length_m`) using calibrated ground-plane world coordinates $(X, Y)$ in metres derived from the accepted Phase 07 homography $H$:
    - When an approach stop line (from `counting_lines`) is associated with the queue zone (via `stop_line_mapping` or shared approach), calculate queue length as the physical Euclidean distance in metres from the stop line reference to the furthest queued vehicle in the zone.
    - When no stop line is configured, calculate queue length as the maximum physical Euclidean distance in metres between any pair of queued vehicles in the zone (queue span).
  - Queue length must never silently fall back to pixel distance. If calibration is unaccepted, missing, or projection fails, store `queue_length_m = NULL` and set `status = 'unavailable'` or `'invalid'`.
  - Persist queue observations to the canonical `queue_events` table with `queue_event_id`, `run_id`, `video_id`, `zone_id`, `approach`, `timestamp_s`, `queue_length_m`, `queued_vehicle_count`, and `status`.
- Explicit constraint: Do NOT compute a final congestion index or score (strictly out of scope).

## Inputs and dependencies
- Phase 01: canonical database connection, schema bootstrap, `videos`, `processing_runs`, provenance tracking.
- Phase 04: ordered trajectory histories, bottom-centre ground contact point convention (`ground_x`, `ground_y`), `build_trajectories()`.
- Phase 05: counting lines (`counting_lines`), queue zones (`zones` with `zone_type = 'queue'`), approach geometry.
- Phase 07: accepted camera calibration (`calibration_runs.accepted = 1`), homography projection functions in `backend.calibration`.
- Phase 08: calibrated speed observations (`speed_observations`), speed threshold conversions, observation quality statuses.

## Database schema and persistence
Prefer no schema change: canonical tables `stop_events` and `queue_events` already exist in `backend/database/schema.sql`:
1. `stop_events`:
   - `stop_event_id`: TEXT PRIMARY KEY (UUID)
   - `run_id`: TEXT NOT NULL REFERENCES processing_runs(run_id)
   - `video_id`: TEXT NOT NULL REFERENCES videos(video_id)
   - `track_id`: INTEGER NOT NULL
   - `start_timestamp_s`: REAL NOT NULL
   - `end_timestamp_s`: REAL
   - `duration_s`: REAL
   - `threshold_kmh`: REAL NOT NULL
   - `status`: TEXT NOT NULL CHECK (status IN ('valid', 'invalid', 'unavailable'))
2. `queue_events`:
   - `queue_event_id`: TEXT PRIMARY KEY (UUID)
   - `run_id`: TEXT NOT NULL REFERENCES processing_runs(run_id)
   - `video_id`: TEXT NOT NULL REFERENCES videos(video_id)
   - `zone_id`: TEXT
   - `approach`: TEXT
   - `timestamp_s`: REAL NOT NULL
   - `queue_length_m`: REAL
   - `queued_vehicle_count`: INTEGER
   - `status`: TEXT NOT NULL CHECK (status IN ('valid', 'invalid', 'unavailable'))

## Configuration
Add a `queue` section to `configs/default.yaml` and validate it in `backend/config.py`:
```yaml
queue:
  stop_speed_threshold_kmh: 5.0
  min_stop_duration_s: 3.0
  min_queue_vehicles: 2
  aggregation_interval_s: 1.0
  max_gap_seconds: 1.0
  stop_line_mapping: {}
```
- `stop_speed_threshold_kmh`: float/int $> 0.0$, speed threshold below which a vehicle is considered stopped (default 5.0 km/h).
- `min_stop_duration_s`: float/int $\ge 0.0$, minimum continuous duration in seconds to classify a stopped event (default 3.0 s).
- `min_queue_vehicles`: integer $\ge 1$, minimum number of stopped vehicles required to form a queue (default 2).
- `aggregation_interval_s`: float/int $> 0.0$, sampling cadence in seconds for evaluating queue states across the timeline (default 1.0 s).
- `max_gap_seconds`: float/int $> 0.0$, maximum time gap between consecutive observations before breaking continuous stopped state (default 1.0 s).
- `stop_line_mapping`: mapping of queue `zone_id` to `line_id` for explicit stop-line relationships (default `{}`).

## Data and metadata
Use canonical field names from `backend/database/schema.sql` and `docs/data_dictionary.md`.
Preserve source video identity, source SHA-256, processing run, model/configuration provenance, and authoritative timestamps where applicable.
Never fall back to nominal FPS or frame counting for elapsed time or duration.
Never fabricate research data (no invented calibration points, ground truth, or measurements; use clearly-labelled software fixtures in tests only).

## Interface contract
- Pure logic module in `backend/queue.py`:
  - `StopEvent`: dataclass matching `stop_events` table with `.to_dict()`.
  - `QueueEvent`: dataclass matching `queue_events` table with `.to_dict()`.
  - `detect_stop_events_for_track(track_id, observations, stop_speed_threshold_kmh, min_stop_duration_s, max_gap_s, run_id, video_id) -> list[StopEvent]`
  - `detect_stop_events_for_tracks(track_observations, stop_speed_threshold_kmh, min_stop_duration_s, max_gap_s, run_id, video_id) -> dict[int, list[StopEvent]]`
  - `compute_queue_length_m(queued_points_world, stop_line_world=None) -> float | None`
  - `detect_queue_events_at_timestamp(timestamp_s, stopped_tracks_at_t, zones, counting_lines, homography_matrix, min_queue_vehicles, stop_line_mapping, run_id, video_id) -> list[QueueEvent]`
  - `evaluate_queue_events_for_run(speed_observations, trajectories, zones, counting_lines, homography_matrix, config, run_id, video_id) -> tuple[list[StopEvent], list[QueueEvent]]`
- Queue service in `backend/services/queue.py`:
  - `run_queue_detection(parent_run_id, calibration_id=None, config=None, repository_root=None, connection=None) -> dict[str, Any]`
  - `get_queue_summary(run_id, config=None, repository_root=None, connection=None) -> dict[str, Any]`
  - `get_stop_events(run_id, track_id=None, limit=None, config=None, repository_root=None, connection=None) -> dict[str, Any]`
  - `get_queue_events(run_id, zone_id=None, approach=None, limit=None, config=None, repository_root=None, connection=None) -> dict[str, Any]`
- Repository operations in `backend/database/repository.py`:
  - `insert_stop_events(connection, rows)`
  - `insert_queue_events(connection, rows)`
  - `fetch_stop_events_for_run(connection, run_id, track_id=None)`
  - `fetch_queue_events_for_run(connection, run_id, zone_id=None, approach=None)`
  - `fetch_queue_detection_stats(connection, run_id)`
- CLI commands in `backend/cli.py`:
  - `traffic-vision detect-queue PARENT_RUN_ID [--calibration-id CALIBRATION_ID] [--config CONFIG]`
  - `traffic-vision show-queue RUN_ID [--zone-id ZONE_ID] [--approach APPROACH] [--limit LIMIT] [--config CONFIG]`
  - `traffic-vision show-stops RUN_ID [--track-id TRACK_ID] [--limit LIMIT] [--config CONFIG]`

## Error handling
Reject or explicitly mark invalid inputs and failed processing:
- Reject non-existent parent runs or uncompleted parent runs.
- Reject unaccepted calibration runs (`accepted = 0`) or missing calibration when calibrated queue length is requested.
- Flag uncalibrated tracks or points with failed world projection as `status = 'unavailable'` or `'invalid'`, with `queue_length_m = NULL`. Never guess or substitute 0 for missing queue lengths.
- Break stopped duration tracking when temporal gap exceeds `max_gap_seconds`.
- Flag non-monotonic or negative time intervals ($\Delta t \le 0$) as `status = 'invalid'`.
- Disallow pixel distance fallback for queue lengths under all circumstances.

## Tests and evidence
Add focused tests in `tests/test_queue.py` and `tests/test_queue_service.py`.
All existing tests and new phase tests must pass (`uv run pytest -q`).
Report raw pytest output in the handoff.
Test fixtures may be synthetic but must be clearly labelled as software fixtures.

## Handoff
Create `docs/handoffs/phase_09/HANDOFF.md` containing changed files, interfaces, schema changes, config keys/defaults, input/output contracts, raw test results, assumptions, limitations, unresolved issues, and dependencies for Phase 10.

## Completion criteria (measurable test plan TP9-01..TP9-16)
- **TP9-01**: Speed threshold boundary: Vehicle speeds $\le \text{stop\_speed\_threshold\_kmh}$ are classified as stopped; speeds above threshold are classified as moving.
- **TP9-02**: Duration accumulation: Sustained stops $\ge \text{min\_stop\_duration\_s}$ produce valid `stop_events` with correct `duration_s`; stops shorter than threshold are not persisted as confirmed stop events.
- **TP9-03**: Temporal gap rule: Temporal gaps exceeding `max_gap_seconds` break stopped duration accumulation and split or terminate stopped episodes.
- **TP9-04**: Non-monotonic / invalid timestamp handling: Non-monotonic or negative intervals are flagged with `status = 'invalid'`.
- **TP9-05**: Minimum queue vehicles boundary: Stopped vehicle counts $< \text{min\_queue\_vehicles}$ record count but yield `queue_length_m = 0.0`.
- **TP9-06**: Queue formation trigger: Stopped vehicle counts $\ge \text{min\_queue\_vehicles}$ in a queue zone trigger queue formation and calculate non-zero queue length.
- **TP9-07**: Queue zone spatial containment: Only vehicles whose bottom-centre ground contact point lies inside the queue zone polygon are counted as queued.
- **TP9-08**: Calibrated world-coordinate queue length: Queue length is computed in metres from calibrated world coordinates $(X, Y)$ using the accepted homography matrix.
- **TP9-09**: Uncalibrated input and no pixel fallback: Missing or unaccepted calibration marks queue length as `queue_length_m = NULL` and `status = 'unavailable'`; pixel fallback is strictly prohibited.
- **TP9-10**: Stop-line distance and ordering: Queue length from a stop line measures the physical distance to the rear-most queued vehicle.
- **TP9-11**: Aggregation interval time slicing: Queue state is evaluated at regular intervals governed by `aggregation_interval_s`.
- **TP9-12**: Database persistence and provenance: `stop_events` and `queue_events` retain `run_id`, `video_id`, `timestamp_s`, and foreign keys to parent run.
- **TP9-13**: Unaccepted calibration rejection: Service rejects unaccepted calibration runs (`accepted = 0`).
- **TP9-14**: Config validation enforces queue parameters: `backend/config.py` validates all `queue` configuration keys and constraints.
- **TP9-15**: CLI commands end-to-end: `traffic-vision detect-queue`, `traffic-vision show-queue`, and `traffic-vision show-stops` execute and return valid JSON.
- **TP9-16**: Signal phase independence: Queue detection executes successfully without external signal controller inputs.

## Explicit exclusions
Final congestion index or score, emission modelling, MCE, redesign, SUMO, model training, dashboard.

## Independent review
Do not perform the final checks or acceptance review in this task. Prompt checking, implementation review, testing review, and completion verification will be performed separately by Pro subagents that are different from the normal implementation model.
Run your own phase tests and report raw output, but do not declare the phase accepted.