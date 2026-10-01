# Phase 02 - YOLO Detection and Preprocessing

## Objective
Implement only YOLO detection, configurable preprocessing, tiled inference/duplicate merging, and explicit vehicle-class mapping. This prompt is independently executable after the stated dependencies are complete.

## Master sections implemented
YOLO detection, configurable preprocessing, tiled inference/duplicate merging, and explicit vehicle-class mapping

## Boundary
Implement nothing except this phase. Do not silently implement later-phase functionality.
Use backend/database/schema.sql and docs/data_dictionary.md as the canonical data contract.
Every derived/result row must retain run_id and relevant source video/frame/timestamp provenance.

## Scope
- Load configurable YOLO model/version.
- Support confidence, IoU/NMS, image size, frame sampling, ROI crop, resize, and optional overlapping tiles.
- Deterministically merge overlapping tile detections.
- Store full detection geometry, class, confidence, frame_number and timestamp.
- Keep detection strictly separate from tracking.
- Define a project class mapping and do not assume COCO has auto-rickshaw.

## Inputs and dependencies
Phase 01 video/config/database contracts.

## Configuration
Model path/version, confidence threshold, IoU/NMS threshold, image size, frame selection, ROI/tiling, tile overlap, and class mapping.

## Data and metadata
Use canonical field names. Preserve source video identity, source SHA-256, processing run, model/configuration provenance, and authoritative timestamps where applicable.
Do not call Ultralytics model.track(); detection is the only CV output in this phase.

## Error handling
Reject or explicitly mark invalid inputs and failed processing. Do not silently drop records, invent measurements, or replace unavailable research values with zero.

## Tests and evidence
Add focused tests for this phase, run them, and report the raw commands/results in the handoff. Test fixtures may be synthetic but must be labelled as software fixtures.

## Handoff
Create docs/handoffs/phase_02/HANDOFF.md containing changed files, interfaces, schema changes, config keys/defaults, input/output contracts, raw test results, assumptions, limitations, unresolved issues, and dependencies for the next phase.

## Completion criteria
Canonical detections are produced for a processing run with no tracker IDs. Tests cover config validation, class mapping, tile merging, empty detections, and deterministic preprocessing.

## Explicit exclusions
ByteTrack, trajectory analytics, counting, movement, calibration, speed, queue, review, active learning, training, dashboard.

## Independent review
Do not perform the final checks or acceptance review in this task. Prompt checking, implementation review, testing review, and completion verification will be performed separately by Pro subagents that are different from the normal implementation model.
Run your own phase tests and report raw output, but do not declare the phase accepted.