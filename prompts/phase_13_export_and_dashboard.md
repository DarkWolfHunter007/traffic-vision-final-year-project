# Phase 13 - Export and Research Dashboard

## Objective
Implement only traceable CSV/JSON/SQLite export and status-aware research dashboard. This prompt is independently executable after the stated dependencies are complete.

## Master sections implemented
traceable CSV/JSON/SQLite export and status-aware research dashboard

## Boundary
Implement nothing except this phase. Do not silently implement later-phase functionality.
Use backend/database/schema.sql and docs/data_dictionary.md as the canonical data contract.
Every derived/result row must retain run_id and relevant source video/frame/timestamp provenance.

## Scope
- Export raw and summary data in CSV, JSON, and SQLite-compatible forms.
- Retain run/video/model/config provenance.
- Produce 15-minute and observed-period summaries.
- Display validation status, tracking quality, review status, speed/queue summaries, and video metadata.
- Distinguish valid, invalid, unavailable, and unvalidated values.

## Inputs and dependencies
All earlier phases and their HANDOFF files.

## Configuration
Export paths/formats, selected run, summary interval, and dashboard display settings.

## Data and metadata
Use canonical field names. Preserve source video identity, source SHA-256, processing run, model/configuration provenance, and authoritative timestamps where applicable.
The dashboard is a research interface, not an acceptance engine.

## Error handling
Reject or explicitly mark invalid inputs and failed processing. Do not silently drop records, invent measurements, or replace unavailable research values with zero.

## Tests and evidence
Add focused tests for this phase, run them, and report the raw commands/results in the handoff. Test fixtures may be synthetic but must be labelled as software fixtures.

## Handoff
Create docs/handoffs/phase_13/HANDOFF.md containing changed files, interfaces, schema changes, config keys/defaults, input/output contracts, raw test results, assumptions, limitations, unresolved issues, and dependencies for the next phase.

## Completion criteria
Tests cover deterministic exports, provenance retention, summary calculations, invalid/unavailable rendering, and correct run selection.

## Explicit exclusions
New CV algorithms, downstream congestion/emission/MCE/SUMO calculations, silent historical repair.

## Independent review
Do not perform the final checks or acceptance review in this task. Prompt checking, implementation review, testing review, and completion verification will be performed separately by Pro subagents that are different from the normal implementation model.
Run your own phase tests and report raw output, but do not declare the phase accepted.