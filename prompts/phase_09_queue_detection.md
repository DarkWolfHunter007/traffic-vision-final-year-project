# Phase 09 — Queue and Stopped-Vehicle Detection

## Objective
Implement only the queue and stopped-vehicle detection stage of Traffic Vision, building on completed earlier phases.

## Scope
- Implement: queue-region/stop-line configuration, configurable speed and duration thresholds, stopped-vehicle detection, and calibrated queue-length estimation.
- Preserve existing module boundaries and source-data traceability.
- Keep configuration explicit and reproducible.
- Add appropriate tests and documentation for this phase.

## Requirements
- Follow the master prompt in prompts/master_prompt.md.
- Do not fabricate unavailable measurements or silently discard failures.
- Preserve source video, frame, timestamp, vehicle/track identity, and configuration metadata wherever applicable.
- Keep research assumptions configurable rather than hidden in code.

## Explicit Exclusions
Do not implement: final congestion index, emission calculations, redesign, MCE, and SUMO.
Do not silently pull functionality from later phases into this phase.

## Deliverables
- Phase implementation.
- Required configuration/schema changes.
- Tests for critical behaviour.
- Documentation/update notes.

## Completion Criteria
Queue observations are reproducible from tracked, calibrated vehicle data using documented thresholds.

## Dependencies
Complete the preceding phases in order. If a dependency is missing or inconsistent, document it rather than bypassing it.

## Independent Review
Do not perform the final checks or acceptance review in this task. Prompt checking, implementation review, testing review, and completion verification will be performed separately by Pro subagents that are different from the normal implementation model.
