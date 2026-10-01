# Phase 09 - Stopped Vehicle and Queue Detection

## Objective
Implement only stopped/slow states and calibrated queue observations. This prompt is independently executable after the stated dependencies are complete.

## Master sections implemented
stopped/slow states and calibrated queue observations

## Boundary
Implement nothing except this phase. Do not silently implement later-phase functionality.
Use backend/database/schema.sql and docs/data_dictionary.md as the canonical data contract.
Every derived/result row must retain run_id and relevant source video/frame/timestamp provenance.

## Scope
- Configure queue zones and stop-line relationships.
- Detect stopped/slow states using speed threshold and minimum duration.
- Calculate queue length from calibrated world coordinates.
- Preserve queued vehicle counts and explicit status.
- Use queue_length_m as the canonical field.

## Inputs and dependencies
Phase 08 speed and Phase 07 accepted calibration.

## Configuration
Speed threshold, minimum stop duration, queue-zone ID, stop-line relationship, and aggregation interval.

## Data and metadata
Use canonical field names. Preserve source video identity, source SHA-256, processing run, model/configuration provenance, and authoritative timestamps where applicable.
Queue length must never silently fall back to pixel distance.

## Error handling
Reject or explicitly mark invalid inputs and failed processing. Do not silently drop records, invent measurements, or replace unavailable research values with zero.

## Tests and evidence
Add focused tests for this phase, run them, and report the raw commands/results in the handoff. Test fixtures may be synthetic but must be labelled as software fixtures.

## Handoff
Create docs/handoffs/phase_09/HANDOFF.md containing changed files, interfaces, schema changes, config keys/defaults, input/output contracts, raw test results, assumptions, limitations, unresolved issues, and dependencies for the next phase.

## Completion criteria
Tests cover threshold boundaries, duration accumulation, queue ordering, world-coordinate distance, and invalid/unavailable cases.

## Explicit exclusions
Final congestion index, emissions, MCE, redesign, SUMO, model training, dashboard.

## Independent review
Do not perform the final checks or acceptance review in this task. Prompt checking, implementation review, testing review, and completion verification will be performed separately by Pro subagents that are different from the normal implementation model.
Run your own phase tests and report raw output, but do not declare the phase accepted.