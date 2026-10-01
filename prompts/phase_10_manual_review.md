# Phase 10 - Manual Review and Human-in-the-Loop Correction

## Objective
Implement only uncertainty review, snippets, and auditable class/bounding-box corrections. This prompt is independently executable after the stated dependencies are complete.

## Master sections implemented
uncertainty review, snippets, and auditable class/bounding-box corrections

## Boundary
Implement nothing except this phase. Do not silently implement later-phase functionality.
Use backend/database/schema.sql and docs/data_dictionary.md as the canonical data contract.
Every derived/result row must retain run_id and relevant source video/frame/timestamp provenance.

## Scope
- Identify configurable low-confidence and other uncertain events.
- Generate configurable before/after event snippets.
- Provide review UI/workflow.
- Preserve original prediction, confidence, and bbox.
- Store corrected class and corrected bbox separately.
- Record review reason/status and source references.

## Inputs and dependencies
Phase 02 detections, Phase 03 tracking, and Phase 01 video/provenance.

## Configuration
Review threshold, snippet before/after duration, allowed classes, and review statuses.

## Data and metadata
Use canonical field names. Preserve source video identity, source SHA-256, processing run, model/configuration provenance, and authoritative timestamps where applicable.
Corrections must contain enough geometry for later detection fine-tuning, not only a class label.

## Error handling
Reject or explicitly mark invalid inputs and failed processing. Do not silently drop records, invent measurements, or replace unavailable research values with zero.

## Tests and evidence
Add focused tests for this phase, run them, and report the raw commands/results in the handoff. Test fixtures may be synthetic but must be labelled as software fixtures.

## Handoff
Create docs/handoffs/phase_10/HANDOFF.md containing changed files, interfaces, schema changes, config keys/defaults, input/output contracts, raw test results, assumptions, limitations, unresolved issues, and dependencies for the next phase.

## Completion criteria
Tests cover uncertainty selection, snippet boundaries, original-prediction preservation, class/box validation, and status transitions.

## Explicit exclusions
Automatic retraining, dataset splitting, production-model replacement, emissions, MCE, redesign, SUMO.

## Independent review
Do not perform the final checks or acceptance review in this task. Prompt checking, implementation review, testing review, and completion verification will be performed separately by Pro subagents that are different from the normal implementation model.
Run your own phase tests and report raw output, but do not declare the phase accepted.