# Traffic Vision Data Dictionary

This document and `backend/database/schema.sql` are the canonical data contract. Phase prompts must reference these definitions instead of inventing field names.

## Naming rules

- `video_id` identifies the source video.
- `run_id` identifies one complete processing configuration/model execution against a video.
- `frame_number` is the source frame index when available; timestamps are authoritative for elapsed time.
- `timestamp_s` is the media timestamp in seconds from the source timeline.
- `ground_x/ground_y` are the configurable bottom-centre ground point of a detection box.
- `world_x/world_y` are calibrated coordinates and must be NULL/unavailable until an accepted calibration exists.
- `queue_length_m` is the canonical queue-length field.
- `corrected_class` and `corrected_bbox_json` are the canonical manual-correction fields.
- `movement` is one of `left`, `through`, `right`, `u_turn`, or `unknown` unless a study configuration explicitly defines another controlled value.
- `run_id` is mandatory on every derived/result table.

## Provenance

Every processing run records:

- source video SHA-256
- model version
- configuration SHA-256
- schema version
- code version where available
- start/end time
- status

Changing thresholds, frame selection, model weights, calibration, or relevant configuration creates a new processing run. Existing result rows are never silently overwritten or mixed across runs.

## Time

Do not derive authoritative elapsed time solely from `frame_number / FPS`. Phase 01 must preserve per-frame/media timestamps where available, detect variable-frame-rate input, and record wall-clock start time when available.

## Geometry

For image-to-ground projection, use the configurable bottom-centre of the vehicle bounding box unless a documented study-specific ground-point method overrides it. The box centre is not the default physical reference point.

## Vehicle classes

The model class IDs and project vehicle classes are separate concepts. Phase 02 must define an explicit mapping/configuration and must not assume COCO contains every Kerala traffic class, including auto-rickshaws.

## Manual corrections

A correction must preserve the original prediction and may include corrected bounding-box geometry, not only a class label. Corrected samples remain traceable to the source video, run, frame/timestamp, and review event.

## Ground truth and splitting

Training/validation/test splits must be made by video segment or source-video group, never by adjacent frames. The initial labelled set must be explicitly documented rather than assumed.
