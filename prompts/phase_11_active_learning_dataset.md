# Phase 11 - Active-Learning Dataset Pipeline

## Objective
Implement only approved correction dataset generation with leakage-safe versioning. This prompt is independently executable after the stated dependencies are complete.

## Master sections implemented
approved correction dataset generation with leakage-safe versioning

## Boundary
Implement nothing except this phase. Do not silently implement later-phase functionality.
Use backend/database/schema.sql and docs/data_dictionary.md as the canonical data contract.
Every derived/result row must retain run_id and relevant source video/frame/timestamp provenance.

## Scope
- Accept only approved corrections.
- Generate detection-training images/labels and metadata.
- Version manifests.
- Split by source video or contiguous source segment, never by adjacent frames.
- Document origin of the initial labelled set.
- Prevent corrected samples from leaking into test data.

## Inputs and dependencies
Phase 10 review contract and Phase 01 provenance.

## Configuration
Dataset root/version, split grouping, sampling policy, duplicate-control policy, and manifest format.

## Data and metadata
Use canonical field names. Preserve source video identity, source SHA-256, processing run, model/configuration provenance, and authoritative timestamps where applicable.
Every sample must retain source video/run/frame/timestamp/review linkage.

## Error handling
Reject or explicitly mark invalid inputs and failed processing. Do not silently drop records, invent measurements, or replace unavailable research values with zero.

## Tests and evidence
Add focused tests for this phase, run them, and report the raw commands/results in the handoff. Test fixtures may be synthetic but must be labelled as software fixtures.

## Handoff
Create docs/handoffs/phase_11/HANDOFF.md containing changed files, interfaces, schema changes, config keys/defaults, input/output contracts, raw test results, assumptions, limitations, unresolved issues, and dependencies for the next phase.

## Completion criteria
Tests cover group-based split leakage, duplicate detection, label generation, manifest reproducibility, and source provenance.

## Explicit exclusions
Reinforcement learning, automatic production replacement, final model selection.

## Independent review
Do not perform the final checks or acceptance review in this task. Prompt checking, implementation review, testing review, and completion verification will be performed separately by Pro subagents that are different from the normal implementation model.
Run your own phase tests and report raw output, but do not declare the phase accepted.