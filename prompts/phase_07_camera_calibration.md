# Phase 07 - Camera Calibration and Diagnostics

## Objective
Implement only validated planar homography calibration with held-out error diagnostics. This prompt is independently executable after the stated dependencies are complete.

## Master sections implemented
validated planar homography calibration with held-out error diagnostics

## Boundary
Implement nothing except this phase. Do not silently implement later-phase functionality.
Use backend/database/schema.sql and docs/data_dictionary.md as the canonical data contract.
Every derived/result row must retain run_id and relevant source video/frame/timestamp provenance.

## Scope
- Require at least six image/world point pairs.
- Hold out one or two points for testing.
- Report mean and maximum held-out reprojection error in metres.
- Reject calibration above a configurable threshold.
- Record flat-road assumption and wide-angle distortion check/status.
- Persist calibration parameters and point roles.

## Inputs and dependencies
Phase 04 bottom-centre convention and Phase 01 provenance.

## Configuration
Minimum point count, held-out count, reprojection threshold, distortion-check state, coordinate system, and flat-road assumption.

## Data and metadata
Use canonical field names. Preserve source video identity, source SHA-256, processing run, model/configuration provenance, and authoritative timestamps where applicable.
Four points with no independent error check are insufficient.

## Error handling
Reject or explicitly mark invalid inputs and failed processing. Do not silently drop records, invent measurements, or replace unavailable research values with zero.

## Tests and evidence
Add focused tests for this phase, run them, and report the raw commands/results in the handoff. Test fixtures may be synthetic but must be labelled as software fixtures.

## Handoff
Create docs/handoffs/phase_07/HANDOFF.md containing changed files, interfaces, schema changes, config keys/defaults, input/output contracts, raw test results, assumptions, limitations, unresolved issues, and dependencies for the next phase.

## Completion criteria
Tests cover homography, held-out error, rejection, insufficient/degenerate points, and persistence. No world coordinates are valid before accepted calibration.

## Explicit exclusions
Speed, queue, counting changes, review, active learning, training, emissions, MCE, SUMO.

## Independent review
Do not perform the final checks or acceptance review in this task. Prompt checking, implementation review, testing review, and completion verification will be performed separately by Pro subagents that are different from the normal implementation model.
Run your own phase tests and report raw output, but do not declare the phase accepted.