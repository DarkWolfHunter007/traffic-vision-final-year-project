# Phase 06 - Vehicle Counting, Movement, and Ground Truth

## Objective
Implement only crossing events, movement derivation, 15-minute traffic bins, vehicles/hour, and the initial counting ground-truth set. This prompt is independently executable after the stated dependencies are complete.

## Master sections implemented
crossing events, movement derivation, 15-minute traffic bins, vehicles/hour, and the initial counting ground-truth set

## Boundary
Implement nothing except this phase. Do not silently implement later-phase functionality.
Use backend/database/schema.sql and docs/data_dictionary.md as the canonical data contract.
Every derived/result row must retain run_id and relevant source video/frame/timestamp provenance.

## Scope
- Establish 2-3 short manually counted clips from different conditions before claiming counting acceptance.
- Record ground-truth counts by approach/movement/class where feasible.
- Detect line crossings and prevent duplicate events.
- Derive movement from configured entry/exit zones, not one line.
- Preserve raw events.
- Aggregate 15-minute bins and observed-period counts.
- Extrapolate vehicles/hour while retaining the observed duration.

## Inputs and dependencies
Phases 03-05 and documented ground-truth clips.

## Configuration
Bin duration defaults to 900 seconds; crossing deduplication, movement, observation-period, and extrapolation rules are configurable.

## Data and metadata
Use canonical field names. Preserve source video identity, source SHA-256, processing run, model/configuration provenance, and authoritative timestamps where applicable.
The ground-truth set is evidence for later evaluation, not proof that the counter passed.

## Error handling
Reject or explicitly mark invalid inputs and failed processing. Do not silently drop records, invent measurements, or replace unavailable research values with zero.

## Tests and evidence
Add focused tests for this phase, run them, and report the raw commands/results in the handoff. Test fixtures may be synthetic but must be labelled as software fixtures.

## Handoff
Create docs/handoffs/phase_06/HANDOFF.md containing changed files, interfaces, schema changes, config keys/defaults, input/output contracts, raw test results, assumptions, limitations, unresolved issues, and dependencies for the next phase.

## Completion criteria
Tests cover no-double-counting, bidirectional lines, entry/exit movement derivation, 15-minute bins, and hourly extrapolation. A predefined counting error tolerance must exist before independent acceptance review.

## Explicit exclusions
Calibration, speed, queue, review, active learning, training, emissions, MCE, redesign, SUMO.

## Independent review
Do not perform the final checks or acceptance review in this task. Prompt checking, implementation review, testing review, and completion verification will be performed separately by Pro subagents that are different from the normal implementation model.
Run your own phase tests and report raw output, but do not declare the phase accepted.