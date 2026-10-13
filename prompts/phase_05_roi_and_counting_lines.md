# Phase 05 — ROI, Entry/Exit Zones, and Counting-Line Configuration

## Objective
Implement only ROI geometry, entry/exit zones, counting-line configuration, approach assignment, configuration persistence, and geometry validation. This prompt is independently executable after the stated dependencies are complete.

## Master sections implemented
ROI geometry, entry/exit zones, counting-line configuration, approach assignment, and configuration persistence

## Boundary
Implement nothing except this phase. Do not silently implement later-phase functionality.
Use `backend/database/schema.sql` and `docs/data_dictionary.md` as the canonical data contract.
`counting_lines` and `zones` are `video_id`-scoped geometry-configuration tables, not derived run results, so they carry `video_id`, `config_version`, and `geometry_sha256` rather than `run_id`.
No schema changes and no new tables: polygonal ROIs and entry/exit zones are stored in the existing `zones` table with `zone_type` in `('entry', 'exit', 'roi', 'queue')`, validated strictly in application code.

## Scope
- Support multiple polygonal ROIs and entry/exit/queue zones stored in the canonical `zones` table.
- Support stable counting-line IDs, approach assignment, direction vectors, and bidirectional settings in `counting_lines`.
- Polygon ROIs represent analytic zones; Phase 02 `detection.roi_crop` remains an independent detection-preprocessing concern.
- Validate all geometries strictly in application code before persistence.
- Persist versioned, immutable configuration: compute deterministic `geometry_sha256` and set `config_version` to its first 12 hex characters.
- Interface: load geometry from a YAML/JSON file via CLI `load-geometry` (idempotent reload).
- Interface: render configurations for researcher inspection via CLI `show-geometry`, which overlays lines and zones on a video frame preview to an image file, creating no `processing_run`.
- Provide a pure helper in `backend/geometry.py` determining which side of a directed line a 2D point lies on.
- Downstream integration: must use `backend/geometry.py` and `build_trajectories()`, never raw database `tracks.trajectory_status`.
- Do not claim that a single counting line determines left/through/right movement (Phase 06 derives movement from entry-to-exit trajectory evidence).

## Inputs and dependencies
- Phase 01: database connection, schema bootstrap, video record (`videos` table), frame access.
- Phase 02: frame dimensions and `frame_stride`.
- Phase 03: track observations in `tracks` table.
- Phase 04: `backend.geometry.compute_ground_point` and `backend.trajectories.build_trajectories()`.

## Configuration and geometry contract
All coordinates are pixel-space floats within video frame bounds `[0, width]` and `[0, height]`.
- `counting_lines.geometry_json` schema:
  ```json
  {
    "endpoints": [[x1, y1], [x2, y2]],
    "direction_vector": [dx, dy]
  }
  ```
  `direction_vector` is `null` for bidirectional lines; unidirectional lines require a non-zero `[dx, dy]` vector defining the forward crossing orientation.
- `zones.geometry_json` schema:
  ```json
  {
    "vertices": [[x1, y1], [x2, y2], ..., [xn, yn]]
  }
  ```
- `config_version` and immutability:
  - `geometry_sha256`: SHA-256 over canonical sorted-key JSON of geometry plus approach and name.
  - `config_version`: first 12 hex characters of `geometry_sha256`.
  - Reloading identical geometry is idempotent (no duplicate rows, no error).
  - Changing geometry creates a new configuration version; existing versions are immutable.

## Data and metadata
Use canonical field names. Preserve source video identity, source SHA-256, configuration provenance, and authoritative timestamps where applicable.
Phase 06 derives movement from entry and exit trajectory evidence.
Downstream code must obtain trajectory status via `build_trajectories()`, never from `tracks.trajectory_status`.

## Validation rules
- Polygons: must have $\ge 3$ distinct vertices, non-zero area, no self-intersection, and all vertices within frame bounds.
- Counting lines: must have exactly 2 distinct endpoints (coincident endpoints rejected) within frame bounds.
- Line direction: bidirectional lines (`bidirectional = 1`) need no direction vector (`direction_vector` is `null`); unidirectional lines (`bidirectional = 0`) require a non-zero `direction_vector`.
- Approaches: all approaches referenced by zones or lines must be declared; entry and exit zones must be associated with a declared approach.
- Zone types: application code validates that `zone_type` is one of `'entry'`, `'exit'`, `'roi'`, or `'queue'`.

## Interface contract
- CLI `traffic-vision load-geometry VIDEO_ID CONFIG_PATH`: loads and validates geometry from YAML/JSON file into `counting_lines` and `zones` tables. Reloading identical geometry is idempotent.
- CLI `traffic-vision show-geometry VIDEO_ID --output OUTPUT_IMAGE [--frame FRAME_NUMBER]`: renders configured lines and zones overlaid on a video frame preview to an image file. Creates no `processing_run`.
- Pure geometry helper in `backend/geometry.py`: determines which side of a directed line a 2D point lies on.

## Error handling
Reject or explicitly mark invalid inputs and failed processing. Reject malformed geometry, out-of-frame coordinates, self-intersecting polygons, zero-area polygons, undeclared approaches, and invalid zone types with clear exceptions. Do not silently drop records, clip coordinates, invent measurements, or replace unavailable research values with zero.

## Tests and evidence
Add focused tests for this phase, run them, and report the raw commands/results in the handoff. Test fixtures may be synthetic but must be labelled as software fixtures. Include an integration test verifying that Phase 04 trajectory ground points from `build_trajectories()` can be tested against a configured counting line.

## Handoff
Create `docs/handoffs/phase_05/HANDOFF.md` containing changed files, interfaces, schema usage, config keys/defaults, input/output contracts, raw test results, assumptions, limitations, unresolved issues, and dependencies for the next phase.

## Completion criteria (measurable test plan TP5-01..TP5-12)
- **TP5-01**: Polygon with $\ge 3$ distinct vertices accepted; $< 3$ vertices rejected.
- **TP5-02**: Self-intersecting polygon rejected; zero-area polygon rejected.
- **TP5-03**: Counting line with 2 distinct endpoints accepted; coincident or missing endpoints rejected.
- **TP5-04**: `geometry_sha256` is deterministic (canonical JSON of geometry + approach + name) and `config_version` is its first 12 hex characters.
- **TP5-05**: Reloading identical geometry configuration is idempotent (preserves existing rows without duplicate rows).
- **TP5-06**: Entry and exit zones assigned to a declared approach; zone referencing undeclared approach rejected.
- **TP5-07**: Bidirectional line allows crossing in both directions without direction vector; unidirectional line requires direction vector and rejects missing/zero vector.
- **TP5-08**: Zone type validation in application code accepts only `entry`, `exit`, `roi`, `queue`; invalid strings rejected.
- **TP5-09**: Geometry rendering via `show-geometry` CLI produces an image overlay with lines and zones on a video frame, creating no `processing_run`.
- **TP5-10**: Integration test: Phase 04 trajectory ground points from `build_trajectories()` can be checked against a configured counting line using pure line-side helper.
- **TP5-11**: Config version immutability: modifying geometry for an existing version is rejected; changed geometry yields a new version.
- **TP5-12**: Multiple ROIs per video accepted; geometry coordinates outside video frame boundaries rejected.

## Explicit exclusions
Crossing events, actual counts, movement derivation (left/through/right), calibration, speed, queue metrics, review, active learning, training, dashboard.

## Independent review
Do not perform the final checks or acceptance review in this task. Prompt checking, implementation review, testing review, and completion verification will be performed separately by Pro subagents that are different from the normal implementation model.
Run your own phase tests and report raw output, but do not declare the phase accepted.