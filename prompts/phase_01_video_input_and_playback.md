# Phase 01 - Video Input, Playback, and Foundational Scaffolding

## Objective
Implement only video ingestion, timestamp handling, foundational configuration, logging, SQLite bootstrap, API/frontend skeleton ownership, and streaming preprocessing infrastructure. This prompt is independently executable after the stated dependencies are complete.

## Master sections implemented
video ingestion, timestamp handling, foundational configuration, logging, SQLite bootstrap, and preprocessing infrastructure

## Boundary
Implement nothing except this phase. Do not silently implement later-phase functionality.
Use backend/database/schema.sql and docs/data_dictionary.md as the canonical data contract.
Every derived/result row must retain run_id and relevant source video/frame/timestamp provenance.

## Scope
- Support MP4, AVI, MOV, and MKV where the installed decoder supports them.
- Extract resolution, nominal FPS, duration, frame count when available, VFR status, source SHA-256, ingestion time, and wall-clock start when available.
- Populate `video_frames(video_id, frame_number, pts_s)` from authoritative decoder/media timestamps where available.
- Provide sequential streaming frame iteration and deterministic frame preview without loading the full source video into RAM.
- Preserve media timestamps; do not use frame_number/FPS as the sole timestamp source.
- Keep raw inputs separate from processed outputs.
- Add config loading and deterministic config hashing.
- Persist the complete canonical run configuration in `processing_runs.config_json`, its hash in `config_hash`, and the current Git commit SHA in required `code_version`.
- Support `parent_run_id` for downstream/reprocessing runs so calibration or analytics changes do not require rerunning upstream detection.
- Add structured logging and database migration/bootstrap support.
- Bootstrap the canonical schema exactly as defined in `backend/database/schema.sql`, including database-enforced status values, foreign keys, timestamp mapping, calibration references, and the single-active-model constraint.
- Establish the minimal API/frontend application skeleton: backend entry point plus health/status endpoint and frontend entry point sufficient to verify application wiring. Do not implement CV-specific API endpoints or dashboard behavior.

## Inputs and dependencies
Baseline repository only. This phase establishes contracts used by all later phases.

## Configuration
Input/raw/processed directories, supported formats, logging level, timestamp strategy, frame sampling, streaming/chunk behavior, CPU/GPU resource policy placeholders, and config-file path.

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
An ingestable video creates canonical `videos`, `video_frames`, and `processing_runs` records. A run stores a complete config snapshot, config hash, required Git code version, and optional parent run. Frame iteration is streaming and does not materialize the full video in memory. The minimal API/frontend skeleton starts successfully and exposes a health/status path. Tests cover metadata, timestamp persistence, hashing, VFR/error handling, config loading, schema constraints/foreign keys, streaming iteration, and application skeleton startup.

## Explicit exclusions
YOLO, ByteTrack, calibration, counting, speed, queue, review, active learning, training, dashboard.

## Independent review
Do not perform the final checks or acceptance review in this task. Prompt checking, implementation review, testing review, and completion verification will be performed separately by Pro subagents that are different from the normal implementation model.
Run your own phase tests and report raw output, but do not declare the phase accepted.
## Pre-Phase-01 gate

Do not begin Phase 01 implementation against an older schema. Before coding, verify that `backend/database/schema.sql` and `docs/data_dictionary.md` are the current canonical versions on the branch. Any existing SQLite database created from the previous schema must be treated as disposable or explicitly migrated before use; Phase 01 must not silently operate against a mismatched schema.
