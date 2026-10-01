# Traffic Vision Independent Review Checklist

This checklist is for the separate review process. Implementation prompts must not declare these checks passed.

## Prompt contract
- [ ] Phase scope is singular and explicit.
- [ ] Master-section references are listed.
- [ ] Dependencies are identified.
- [ ] Later-phase exclusions are explicit.
- [ ] Canonical schema/data dictionary is referenced.
- [ ] Provenance requirements are referenced.
- [ ] Completion criteria are measurable.
- [ ] Required HANDOFF.md contents are defined.

## Implementation review
- [ ] Only the assigned phase was implemented.
- [ ] No later-phase functionality was silently introduced.
- [ ] Interfaces match earlier-phase HANDOFF.md files.
- [ ] Configuration is explicit and reproducible.
- [ ] Canonical field names are used.

## Data integrity
- [ ] Source video SHA-256 is preserved.
- [ ] Every derived/result row has run_id.
- [ ] Model version and configuration hash are traceable.
- [ ] Original predictions remain separate from corrections.
- [ ] Invalid/unavailable measurements are represented explicitly.
- [ ] No measurements are fabricated.

## Computer-vision methodology
- [ ] Bottom-centre ground point is used where physical projection is required.
- [ ] Calibration uses held-out points and reports reprojection error.
- [ ] Variable-frame-rate timestamps are handled.
- [ ] Tracker time parameters are defined independently of processing frame skip.
- [ ] Detection and tracking remain separate layers.
- [ ] Vehicle-class mapping is explicit.
- [ ] Bounding-box corrections are retained.

## Validation
- [ ] Ground-truth clips are identified and documented.
- [ ] Counting acceptance tolerance is defined before acceptance.
- [ ] Tracking quality criteria and ID-switch measurement are defined.
- [ ] Dataset splitting is by video/segment group, not frame.

## Testing review
- [ ] Phase tests exist.
- [ ] Raw test output is reported.
- [ ] Failure cases are covered.
- [ ] No implementation model claims independent acceptance.

## Handoff review
- [ ] HANDOFF.md exists for the phase.
- [ ] Interfaces and schema changes are documented.
- [ ] Configuration keys are listed.
- [ ] Known limitations and unresolved issues are listed.
- [ ] Next phase dependencies are explicit.
