# Phase 01 - Video Input, Playback, and Foundational Scaffolding

## Objective
Implement only video ingestion, timestamp handling, foundational configuration, logging, SQLite bootstrap, and preprocessing infrastructure. This prompt is independently executable after the stated dependencies are complete.

## Master sections implemented
video ingestion, timestamp handling, foundational configuration, logging, SQLite bootstrap, and preprocessing infrastructure

## Boundary
Implement nothing except this phase. Do not silently implement later-phase functionality.
Use backend/database/schema.sql and docs/data_dictionary.md as the canonical data contract.
Every derived/result row must retain run_id and relevant source video/frame/timestamp provenance.

## Scope
- Support MP4, AVI, MOV, and MKV where the installed decoder supports them.
- Extract resolution, nominal FPS, duration, frame count when available, VFR status, source SHA-256, ingestion time, and wall-clock start when available.
- Provide sequential frame iteration and deterministic frame preview.
- Preserve media timestamps; do not use frame_number/FPS as the sole timestamp source.
- Keep raw inputs separate from processed outputs.
- Add config loading and deterministic config hashing.
- Add structured logging and database migration/bootstrap support.

## Inputs and dependencies
Baseline repository only. This phase establishes contracts used by all later phases.

## Configuration
Input/raw/processed directories, supported formats, logging level, timestamp strategy, frame sampling, and config-file path.

## Data and metadata
Use canonical field names. Preserve source video identity, source SHA-256, processing run, model/configuration provenance, and authoritative timestamps where applicable.
Phase 01 owns the initial schema bootstrap, but must use the canonical schema rather than redefining it.

## Error handling
Reject or explicitly mark invalid inputs and failed processing. Do not silently drop records, invent measurements, or replace unavailable research values with zero.

## Tests and evidence
Add focused tests for this phase, run them, and report the raw commands/results in the handoff. Test fixtures may be synthetic but must be labelled as software fixtures.

## Handoff
Create docs/handoffs/phase_01/HANDOFF.md containing changed files, interfaces, schema changes, config keys/defaults, input/output contracts, raw test results, assumptions, limitations, unresolved issues, and dependencies for the next phase.

## Completion criteria
An ingestable video creates a canonical videos row and a reproducible processing-run foundation; timestamps remain correct when frames are skipped. Tests cover metadata, hashing, VFR/error handling, config loading, and schema bootstrap.

## Explicit exclusions
YOLO, ByteTrack, calibration, counting, speed, queue, review, active learning, training, dashboard.

## Independent review
Do not perform the final checks or acceptance review in this task. Prompt checking, implementation review, testing review, and completion verification will be performed separately by Pro subagents that are different from the normal implementation model.
Run your own phase tests and report raw output, but do not declare the phase accepted.