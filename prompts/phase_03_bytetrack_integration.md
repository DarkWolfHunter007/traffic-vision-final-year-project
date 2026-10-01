# Phase 03 - ByteTrack Integration

## Objective
Implement only direct ByteTrack association, track lifecycle, persistent IDs, and tracking-quality instrumentation. This prompt is independently executable after the stated dependencies are complete.

## Master sections implemented
direct ByteTrack association, track lifecycle, persistent IDs, and tracking-quality instrumentation

## Boundary
Implement nothing except this phase. Do not silently implement later-phase functionality.
Use backend/database/schema.sql and docs/data_dictionary.md as the canonical data contract.
Every derived/result row must retain run_id and relevant source video/frame/timestamp provenance.

## Scope
- Consume Phase 02 detections directly through the tracker layer.
- Use Ultralytics ByteTrack directly rather than model.track().
- Maintain track creation, continuation, temporary misses, and termination.
- Instrument ID switches and track continuity.
- Express intended time-based tracker settings in seconds and convert to frame-based internals using actual processing cadence.

## Inputs and dependencies
Phase 01 timestamps/config and Phase 02 detections.

## Configuration
Tracker thresholds and intended time durations; processing cadence/frame-skip information must be available.

## Data and metadata
Use canonical field names. Preserve source video identity, source SHA-256, processing run, model/configuration provenance, and authoritative timestamps where applicable.
Do not fabricate continuity across gaps; incomplete trajectories remain identifiable.

## Error handling
Reject or explicitly mark invalid inputs and failed processing. Do not silently drop records, invent measurements, or replace unavailable research values with zero.

## Tests and evidence
Add focused tests for this phase, run them, and report the raw commands/results in the handoff. Test fixtures may be synthetic but must be labelled as software fixtures.

## Handoff
Create docs/handoffs/phase_03/HANDOFF.md containing changed files, interfaces, schema changes, config keys/defaults, input/output contracts, raw test results, assumptions, limitations, unresolved issues, and dependencies for the next phase.

## Completion criteria
Tests demonstrate persistent IDs on controlled sequences, missed detections, lifecycle handling, frame-skip/time conversion, and ID-switch instrumentation. No research acceptance threshold is invented here.

## Explicit exclusions
Movement, counting, calibration, speed, queue, review, active learning, training, dashboard.

## Independent review
Do not perform the final checks or acceptance review in this task. Prompt checking, implementation review, testing review, and completion verification will be performed separately by Pro subagents that are different from the normal implementation model.
Run your own phase tests and report raw output, but do not declare the phase accepted.