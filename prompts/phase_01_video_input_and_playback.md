# Phase 01 — Video Input and Playback

## Objective
Implement only the video input and playback stage of Traffic Vision, building on completed earlier phases.

## Scope
- Implement: video ingestion, metadata extraction, deterministic frame access, timestamp calculation, and basic playback/frame preview.
- Preserve existing module boundaries and source-data traceability.
- Keep configuration explicit and reproducible.
- Add appropriate tests and documentation for this phase.

## Requirements
- Follow the master prompt in prompts/master_prompt.md.
- Do not fabricate unavailable measurements or silently discard failures.
- Preserve source video, frame, timestamp, vehicle/track identity, and configuration metadata wherever applicable.
- Keep research assumptions configurable rather than hidden in code.

## Explicit Exclusions
Do not implement: YOLO, ByteTrack, calibration, counting, speed, queue detection, manual review, active learning, emissions, SUMO, and the final dashboard.
Do not silently pull functionality from later phases into this phase.

## Deliverables
- Phase implementation.
- Required configuration/schema changes.
- Tests for critical behaviour.
- Documentation/update notes.

## Completion Criteria
A supported CCTV file can be imported, inspected, played/previewed, and its metadata retrieved without loading the complete video into memory.

## Dependencies
Complete the preceding phases in order. If a dependency is missing or inconsistent, document it rather than bypassing it.

## Independent Review
Do not perform the final checks or acceptance review in this task. Prompt checking, implementation review, testing review, and completion verification will be performed separately by Pro subagents that are different from the normal implementation model.
