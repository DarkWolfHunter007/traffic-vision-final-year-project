# Phase 12 - Model Fine-Tuning and Evaluation

## Objective
Implement only candidate YOLO training, model versioning, detection evaluation, tracking evaluation, and counting validation. This prompt is independently executable after the stated dependencies are complete.

## Master sections implemented
candidate YOLO training, model versioning, detection evaluation, tracking evaluation, and counting validation

## Boundary
Implement nothing except this phase. Do not silently implement later-phase functionality.
Use backend/database/schema.sql and docs/data_dictionary.md as the canonical data contract.
Every derived/result row must retain run_id and relevant source video/frame/timestamp provenance.

## Scope
- Train candidate YOLO versions from versioned datasets.
- Record model SHA-256/version and dataset version.
- Report precision/recall/mAP/confusion matrix where labels support them.
- Compare models without overwriting previous versions.
- Measure ID switches and track continuity on documented clips.
- Evaluate counting against Phase 06 ground truth using predefined absolute/percentage error tolerances.
- Evaluate speed/queue only when reference data exists.
- Require explicit selection before changing the active model.

## Inputs and dependencies
Phase 11 dataset, Phase 06 ground truth, and Phase 03 tracking-quality instrumentation.

## Configuration
Training hyperparameters, dataset version, model path/version, random seed where applicable, evaluation thresholds, and active-model selection state.

## Data and metadata
Use canonical field names. Preserve source video identity, source SHA-256, processing run, model/configuration provenance, and authoritative timestamps where applicable.
Do not report metrics that were not actually measured.

## Error handling
Reject or explicitly mark invalid inputs and failed processing. Do not silently drop records, invent measurements, or replace unavailable research values with zero.

## Tests and evidence
Add focused tests for this phase, run them, and report the raw commands/results in the handoff. Test fixtures may be synthetic but must be labelled as software fixtures.

## Handoff
Create docs/handoffs/phase_12/HANDOFF.md containing changed files, interfaces, schema changes, config keys/defaults, input/output contracts, raw test results, assumptions, limitations, unresolved issues, and dependencies for the next phase.

## Completion criteria
Tests cover version registration, reproducible configuration, metric aggregation, comparison, and active-model safeguards. Raw evaluation output is retained; research acceptance remains external.

## Explicit exclusions
Emissions, congestion index, redesign, MCE, SUMO, silent active-model replacement.

## Independent review
Do not perform the final checks or acceptance review in this task. Prompt checking, implementation review, testing review, and completion verification will be performed separately by Pro subagents that are different from the normal implementation model.
Run your own phase tests and report raw output, but do not declare the phase accepted.