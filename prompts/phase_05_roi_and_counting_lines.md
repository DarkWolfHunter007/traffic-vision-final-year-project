# Phase 05 - ROI, Entry/Exit Zones, and Counting-Line Configuration

## Objective
Implement only ROI geometry, entry/exit zones, counting-line configuration, approach assignment, and configuration persistence. This prompt is independently executable after the stated dependencies are complete.

## Master sections implemented
ROI geometry, entry/exit zones, counting-line configuration, approach assignment, and configuration persistence

## Boundary
Implement nothing except this phase. Do not silently implement later-phase functionality.
Use backend/database/schema.sql and docs/data_dictionary.md as the canonical data contract.
Every derived/result row must retain run_id and relevant source video/frame/timestamp provenance.

## Scope
- Support multiple polygonal ROIs.
- Support stable counting-line IDs, direction/bidirectional settings, and approaches.
- Add explicit entry and exit zones for approaches.
- Validate geometry and persist versioned configuration.
- Render configurations for researcher inspection.
- Do not claim that one line determines left/through/right movement.

## Inputs and dependencies
Phase 04 track/ground-point interfaces and Phase 01 persistence.

## Configuration
Geometry, approach names, line direction, bidirectionality, zone type, and configuration version.

## Data and metadata
Use canonical field names. Preserve source video identity, source SHA-256, processing run, model/configuration provenance, and authoritative timestamps where applicable.
Phase 06 derives movement from entry and exit trajectory evidence.

## Error handling
Reject or explicitly mark invalid inputs and failed processing. Do not silently drop records, invent measurements, or replace unavailable research values with zero.

## Tests and evidence
Add focused tests for this phase, run them, and report the raw commands/results in the handoff. Test fixtures may be synthetic but must be labelled as software fixtures.

## Handoff
Create docs/handoffs/phase_05/HANDOFF.md containing changed files, interfaces, schema changes, config keys/defaults, input/output contracts, raw test results, assumptions, limitations, unresolved issues, and dependencies for the next phase.

## Completion criteria
Tests cover geometry validation, reload, entry/exit assignment, line direction, and versioning.

## Explicit exclusions
Crossing events, actual counts, movement derivation, calibration, speed, queue, review, active learning, training, dashboard.

## Independent review
Do not perform the final checks or acceptance review in this task. Prompt checking, implementation review, testing review, and completion verification will be performed separately by Pro subagents that are different from the normal implementation model.
Run your own phase tests and report raw output, but do not declare the phase accepted.