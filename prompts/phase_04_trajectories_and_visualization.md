# Phase 04 - Trajectories and Visualization

## Objective
Implement only ordered trajectory histories, bottom-centre ground points, and visualization. This prompt is independently executable after the stated dependencies are complete.

## Master sections implemented
ordered trajectory histories, bottom-centre ground points, and visualization

## Boundary
Implement nothing except this phase. Do not silently implement later-phase functionality.
Use backend/database/schema.sql and docs/data_dictionary.md as the canonical data contract.
Every derived/result row must retain run_id and relevant source video/frame/timestamp provenance.

## Scope
- Build ordered histories by run_id and track_id.
- Compute bottom-centre as the default ground point.
- Preserve original bbox coordinates separately.
- Render bbox, class, confidence, ID, trajectory trails, and configured overlays.
- Expose incomplete tracks and tracking-quality indicators.

## Inputs and dependencies
Phase 03 tracking and Phase 01 timestamps.

## Configuration
Ground-point method defaults to bottom_center; overlay visibility is configurable.

## Data and metadata
Use canonical field names. Preserve source video identity, source SHA-256, processing run, model/configuration provenance, and authoritative timestamps where applicable.
The bbox centre must not be used as the default physical road point.

## Error handling
Reject or explicitly mark invalid inputs and failed processing. Do not silently drop records, invent measurements, or replace unavailable research values with zero.

## Tests and evidence
Add focused tests for this phase, run them, and report the raw commands/results in the handoff. Test fixtures may be synthetic but must be labelled as software fixtures.

## Handoff
Create docs/handoffs/phase_04/HANDOFF.md containing changed files, interfaces, schema changes, config keys/defaults, input/output contracts, raw test results, assumptions, limitations, unresolved issues, and dependencies for the next phase.

## Completion criteria
Tests cover bottom-centre geometry, ordering, incomplete tracks, overlay toggles, and deterministic rendering inputs.

## Explicit exclusions
Calibration, speed, queue, counting analytics, movement derivation, review, active learning, training, dashboard.

## Independent review
Do not perform the final checks or acceptance review in this task. Prompt checking, implementation review, testing review, and completion verification will be performed separately by Pro subagents that are different from the normal implementation model.
Run your own phase tests and report raw output, but do not declare the phase accepted.