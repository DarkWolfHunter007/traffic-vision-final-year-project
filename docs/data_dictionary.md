# Traffic Vision Data Dictionary

This document and `backend/database/schema.sql` are the canonical data contract. Phase prompts must reference these definitions instead of inventing field names.

## Naming rules

- `video_id` identifies the source video.
- `run_id` identifies one reproducible processing execution against a video. `parent_run_id` links a derived/reprocessed run to the run it was derived from without forcing upstream work to be repeated.
- `frame_number` is the source frame index when available; timestamps are authoritative for elapsed time.
- `timestamp_s` is the media timestamp in seconds from the source timeline.
- `ground_x/ground_y` are the configurable bottom-centre ground point of a detection box.
- `world_x/world_y` are calibrated coordinates and must be NULL/unavailable until an accepted calibration exists.
- `queue_length_m` is the canonical queue-length field.
- `corrected_class` and `corrected_bbox_json` are the canonical manual-correction fields.
- `movement` is one of `left`, `through`, `right`, `u_turn`, or `unknown` unless a study configuration explicitly defines another controlled value.
- `run_id` is mandatory on every derived/result table.
- `parent_run_id` is nullable for root runs and points to the immediate upstream processing run when a later analysis/calibration/configuration run reuses prior outputs.
- `config_json` stores the canonical configuration snapshot for the run; `config_hash` identifies that exact snapshot.
- `code_version` is required and must be the Git commit SHA used to produce the run.
- `model_version`, when present, must reference a registered row in `model_versions`.

## Provenance

Every processing run records:

- source video SHA-256
- model version
- configuration SHA-256
- schema version
- required Git code version SHA
- start/end time
- status

Changing thresholds, frame selection, model weights, calibration, or relevant configuration creates a new processing run. A downstream-only change must reference its upstream run through `parent_run_id` so existing detections/tracks can be reused without rerunning YOLO. Existing result rows are never silently overwritten or mixed across runs.

## Time

Do not derive authoritative elapsed time solely from `frame_number / FPS`. Phase 01 must preserve per-frame/media timestamps where available in `video_frames(video_id, frame_number, pts_s)`, detect variable-frame-rate input, and record wall-clock start time when available. Downstream speed, duration, binning, and event timing must use `pts_s`/`timestamp_s`, never a reconstructed frame-number/FPS timestamp.

## Geometry

For image-to-ground projection, use the configurable bottom-centre of the vehicle bounding box unless a documented study-specific ground-point method overrides it. The box centre is not the default physical reference point.

## Vehicle classes

The model class IDs and project vehicle classes are separate concepts. Phase 02 must define an explicit mapping/configuration and must not assume COCO contains every Kerala traffic class, including auto-rickshaws.

## Manual corrections

A correction must preserve the original prediction and may include corrected bounding-box geometry, not only a class label. Corrected samples remain traceable to the source video, run, frame/timestamp, reviewer, review time, and review event. `manual_reviews` stores the snippet path when a review clip is generated.

## Ground truth and splitting

Training/validation/test splits must be made by video segment or source-video group, never by adjacent frames. The initial labelled set must be explicitly documented rather than assumed.

## Phase 01 database invariants

The SQLite schema must enforce these invariants rather than relying only on application code:

- processing-run status is one of `created`, `running`, `completed`, `failed`, or `cancelled`
- trajectory status is one of `active`, `complete`, `fragmented`, or `invalid`
- result validity status is one of `valid`, `invalid`, or `unavailable`
- model selection is boolean and at most one model may be marked `selected_for_production = 1`
- speed observations require a calibration reference through `calibration_id`
- calibrated world coordinates retain their calibration reference
- counting-event rows retain the counting-line configuration version used to create them
- geometry definitions carry a deterministic geometry hash so a changed line/zone is a new immutable configuration state

## Frame timestamps

`video_frames` is the authoritative frame-to-media-time mapping. It is populated by Phase 01 from the decoder/media timeline. A frame may be sampled or skipped for inference without deleting its source timestamp. If a decoder cannot provide reliable timestamps, the video must be marked accordingly and downstream phases must not silently synthesize authoritative timing from nominal FPS.

## Phase ownership: API and frontend skeleton

Phase 01 owns only the minimal API/frontend skeleton needed to establish repository wiring, health/status endpoints, configuration visibility, and a stable application entry point. It does not implement phase-specific CV endpoints, dashboard features, or business logic. Later phases own their domain endpoints and UI behavior.

## Phase 06 counting, volume bins, and ground truth

- `video_segments`: canonical video segment boundaries for manual counts and dataset splitting.
  - `segment_id`: stable text primary key.
  - `video_id`: foreign key referencing `videos(video_id)`.
  - `start_s` / `end_s`: segment time interval in seconds from source video timeline.
  - `start_frame` / `end_frame`: segment frame index bounds.
  - `label`: optional descriptive label (e.g. "peak_morning", "rain_interval").
  - `condition_notes`: optional researcher notes on lighting, weather, or occlusions.
- `ground_truth_counts`:
  - `video_segment_id`: enforced foreign key referencing `video_segments(segment_id)`.
  - `approach`: declared intersection approach name.
  - `movement`: turning movement (`left`, `through`, `right`, `u_turn`, or `unknown`).
  - `vehicle_class`: vehicle category (e.g. "car", "bus", "auto_rickshaw").
  - `observed_count`: integer manual reference count.
- `crossing_events`:
  - `deduplicated`: integer boolean (0 or 1). `0` indicates a primary countable crossing; `1` indicates a duplicate re-entry within `min_reentry_gap_s` or non-countable event. Raw events are preserved; nothing is silently dropped.
- `traffic_volume_bins`:
  - `bin_start_s`: start of 15-minute aggregation window (`k * bin_duration_s`).
  - `bin_duration_s`: configured bin duration (default 900.0 s).
  - `observed_duration_s`: actual observed duration in seconds within the bin. Truncated or partial final bins retain their actual observed elapsed time.
  - `extrapolated_vehicles_per_hour`: extrapolated rate `count * 3600 / observed_duration_s`. `NULL` when `observed_duration_s == 0`.

## Phase 08 speed observations

- `speed_observations`: canonical vehicle speed observations in calibrated physical units.
  - `speed_observation_id`: stable text primary key (UUID).
  - `run_id`: foreign key referencing `processing_runs(run_id)`.
  - `video_id`: foreign key referencing `videos(video_id)`.
  - `track_id`: integer vehicle track identifier.
  - `timestamp_s`: authoritative media timestamp from source timeline.
  - `speed_mps`: speed in metres per second, or NULL when status is not 'valid'.
  - `speed_kmh`: speed in kilometres per hour (`speed_mps * 3.6`), or NULL when status is not 'valid'.
  - `calibration_id`: foreign key referencing accepted `calibration_runs(calibration_id)`.
  - `status`: observation status, one of `'valid'`, `'invalid'`, or `'unavailable'`.
  - `smoothing_window`: temporal smoothing window duration in seconds.
  - `ground_point_method`: method used for road contact point projection (`'bottom_center'`).

## Phase 09 stopped vehicles and queue observations

- `stop_events`: canonical detected stopped episodes for individual vehicle tracks.
  - `stop_event_id`: stable text primary key (UUID).
  - `run_id`: foreign key referencing `processing_runs(run_id)`.
  - `video_id`: foreign key referencing `videos(video_id)`.
  - `track_id`: integer vehicle track identifier.
  - `start_timestamp_s`: authoritative media timestamp when stopped state began.
  - `end_timestamp_s`: authoritative media timestamp when stopped state ended.
  - `duration_s`: total stopped duration in seconds (`end_timestamp_s - start_timestamp_s`).
  - `threshold_kmh`: configured speed threshold in km/h used to classify stopped state.
  - `status`: observation status, one of `'valid'`, `'invalid'`, or `'unavailable'`.
- `queue_events`: canonical queue observations across designated queue zones and approaches.
  - `queue_event_id`: stable text primary key (UUID).
  - `run_id`: foreign key referencing `processing_runs(run_id)`.
  - `video_id`: foreign key referencing `videos(video_id)`.
  - `zone_id`: nullable identifier of queue zone referencing `zones(zone_id)`.
  - `approach`: declared intersection approach name.
  - `timestamp_s`: authoritative media timestamp from source timeline for the evaluation instant.
  - `queue_length_m`: calibrated physical queue length in metres; NULL when status is not 'valid'.
  - `queued_vehicle_count`: integer count of stopped vehicles forming the queue in the zone.
  - `status`: observation status, one of `'valid'`, `'invalid'`, or `'unavailable'`.

## Phase 10 manual reviews and human-in-the-loop corrections

- `manual_reviews`: canonical auditable human review and correction records.
  - `review_id`: stable text primary key (UUID).
  - `run_id`: foreign key referencing `processing_runs(run_id)`.
  - `video_id`: foreign key referencing `videos(video_id)`.
  - `track_id`: nullable integer vehicle track identifier referencing vehicle track.
  - `detection_id`: nullable text detection identifier referencing `detections(detection_id)`.
  - `frame_number`: integer frame index.
  - `timestamp_s`: authoritative media timestamp in seconds from source timeline.
  - `original_class`: nullable original predicted vehicle class.
  - `corrected_class`: nullable human-corrected vehicle class from `review.allowed_classes`.
  - `original_bbox_json`: nullable JSON string storing original bounding box `{"x1": ..., "y1": ..., "x2": ..., "y2": ...}`.
  - `corrected_bbox_json`: nullable JSON string storing corrected bounding box `{"x1": ..., "y1": ..., "x2": ..., "y2": ...}`.
  - `reason`: mandatory text explanation for review (e.g. `'low_confidence'`, `'class_ambiguity'`, `'boundary_drift'`).
  - `review_status`: review lifecycle status, constrained to `'pending'`, `'approved'`, or `'rejected'`.
  - `reviewer`: mandatory text identifier of human reviewer or audit agent.
  - `reviewed_at`: mandatory authoritative ISO 8601 UTC timestamp.
  - `snippet_path`: nullable file path to extracted before/after event snippet video clip.



