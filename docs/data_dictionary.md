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
- code version where available
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
