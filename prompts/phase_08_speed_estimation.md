# Phase 08 - Speed Estimation

## Objective
Implement only calibrated world-coordinate speed estimation using authoritative timestamps. This prompt is independently executable after the stated dependencies are complete.

## Master sections implemented
calibrated world-coordinate speed estimation using authoritative timestamps

## Boundary
Implement nothing except this phase. Do not silently implement later-phase functionality.
Use backend/database/schema.sql and docs/data_dictionary.md as the canonical data contract.
Every derived/result row must retain run_id and relevant source video/frame/timestamp provenance.

## Scope
- Transform bottom-centre trajectory points through an accepted calibration.
- Compute distance over elapsed media time.
- Convert m/s to km/h.
- Apply configurable smoothing and validity rules.
- Mark insufficient/noisy/unavailable values explicitly.
- Preserve calibration and run provenance.

## Inputs and dependencies
Accepted Phase 07 calibration and Phase 04 trajectory/timestamp contract.

## Configuration
Smoothing window, minimum distance/time separation, outlier handling, and validity thresholds.

## Data and metadata
Use canonical field names. Preserve source video identity, source SHA-256, processing run, model/configuration provenance, and authoritative timestamps where applicable.
Never fall back to nominal FPS when authoritative timestamps are available.

## Error handling
Reject or explicitly mark invalid inputs and failed processing. Do not silently drop records, invent measurements, or replace unavailable research values with zero.

## Tests and evidence
Add focused tests for this phase, run them, and report the raw commands/results in the handoff. Test fixtures may be synthetic but must be labelled as software fixtures.

## Handoff
Create docs/handoffs/phase_08/HANDOFF.md containing changed files, interfaces, schema changes, config keys/defaults, input/output contracts, raw test results, assumptions, limitations, unresolved issues, and dependencies for the next phase.

## Completion criteria
Tests cover distance/time, units, smoothing, timestamp gaps, invalid calibration, and unavailable statuses. Accuracy against reference speeds is a later validation activity.

## Explicit exclusions
Queue, review, active learning, training, emissions, MCE, redesign, SUMO.

## Independent review
Do not perform the final checks or acceptance review in this task. Prompt checking, implementation review, testing review, and completion verification will be performed separately by Pro subagents that are different from the normal implementation model.
Run your own phase tests and report raw output, but do not declare the phase accepted.