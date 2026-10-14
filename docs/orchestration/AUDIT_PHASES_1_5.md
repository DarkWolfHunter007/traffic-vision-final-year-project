# Independent Audit: Phases 1–4 Implementation & Phase 5 Prompt Readiness

**Auditor**: Independent AI (Claude Opus 4.6 Thinking)
**Date**: 2026-10-13
**Scope**: Phases 1–4 implementation vs. phase prompts; Phase 5 prompt readiness
**Branch**: current working tree
**Rule**: NO source, test, or prompt files were modified

---

## 0. Raw Test Output

```text
$ uv run pytest -q
........................................................................ [ 94%]
....                                                                     [100%]
76 passed in 6.61s
```

```text
$ uv run pytest -v
platform win32 -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0
testpaths: tests
plugins: anyio-4.15.1

tests/test_app.py::test_health_endpoint_reports_phase_one PASSED         [  1%]
tests/test_app.py::test_status_endpoint_is_phase_one_only PASSED         [  2%]
tests/test_config.py::test_config_hash_is_stable_for_equivalent_mappings PASSED [  3%]
tests/test_config.py::test_config_rejects_non_decoder_pts_strategy PASSED [  5%]
tests/test_database.py::test_bootstrap_enables_foreign_keys_on_every_connection PASSED [  6%]
tests/test_database.py::test_bootstrap_is_idempotent PASSED              [  7%]
tests/test_database.py::test_bootstrap_rejects_a_database_with_an_unknown_schema PASSED [  9%]
tests/test_detection.py::test_mapping_requires_explicit_project_class PASSED [ 10%]
tests/test_detection.py::test_tile_generation_covers_frame_edges_deterministically PASSED [ 11%]
tests/test_detection.py::test_tile_merge_is_class_aware_and_deterministic PASSED [ 13%]
tests/test_detection.py::test_roi_crop_validates_and_preserves_offsets PASSED [ 14%]
tests/test_detection_service.py::test_detection_run_persists_only_canonical_detections PASSED [ 15%]
tests/test_ingestion.py::test_ingestion_persists_metadata_run_and_decoder_pts PASSED [ 17%]
tests/test_ingestion.py::test_preview_decodes_one_requested_frame_sequentially PASSED [ 18%]
tests/test_media.py::test_timestamp_audit_marks_variable_cadence PASSED  [ 19%]
tests/test_media.py::test_timestamp_audit_marks_missing_or_non_monotonic_pts PASSED [ 21%]
tests/test_phase_04_audit.py::test_audit_cross_run_track_id_collision PASSED [ 22%]
tests/test_phase_04_audit.py::test_audit_active_status_precedence_over_internal_gaps PASSED [ 23%]
tests/test_phase_04_audit.py::test_audit_motion_trail_connects_across_unobserved_gaps PASSED [ 25%]
tests/test_phase_04_audit.py::test_audit_motion_trail_short_continuous_gap_renders_trail PASSED [ 26%]
tests/test_phase_04_audit.py::test_audit_motion_trail_intentional_frame_stride PASSED [ 27%]
tests/test_phase_04_audit.py::test_audit_motion_trail_segments_around_gap PASSED [ 28%]
tests/test_phase_04_audit.py::test_audit_zero_area_bounding_box PASSED   [ 30%]
tests/test_phase_04_audit.py::test_audit_stride_aware_gap_accounting PASSED [ 31%]
tests/test_phase_04_audit.py::test_audit_corrupt_stored_ground_coordinates_rejected PASSED [ 32%]
tests/test_phase_04_audit.py::test_audit_negative_and_nonfinite_timestamps_rejected PASSED [ 34%]
tests/test_phase_04_audit.py::test_audit_interior_termination_semantics PASSED [ 35%]
tests/test_phase_04_audit.py::test_audit_visualization_frame_range_validation PASSED [ 36%]
tests/test_phase_04_audit.py::test_audit_one_frame_range_preview_and_video PASSED [ 38%]
tests/test_phase_04_audit.py::test_audit_trail_gap_exact_boundary PASSED [ 39%]
tests/test_phase_04_audit.py::test_audit_trail_gap_large_frame_stride_splits_all_samples PASSED [ 40%]
tests/test_phase_04_audit.py::test_audit_ground_point_tolerance PASSED   [ 42%]
tests/test_phase_04_audit.py::test_audit_interior_termination_boundary_margin PASSED [ 43%]
tests/test_phase_04_audit.py::test_audit_stride_off_grid_gaps_current_behavior PASSED [ 44%]
tests/test_tracking.py::test_cadence_to_frames_conversion PASSED         [ 46%]
tests/test_tracking.py::test_detection_batch_properties_and_slicing PASSED [ 47%]
tests/test_tracking.py::test_persistent_id_association_across_frames PASSED [ 48%]
tests/test_tracking.py::test_empty_frame_handling PASSED                 [ 50%]
tests/test_tracking.py::test_missed_detection_reconnection_within_buffer PASSED [ 51%]
tests/test_tracking.py::test_evaluate_id_switches_known_switch_and_no_switch PASSED [ 52%]
tests/test_tracking.py::test_resolve_track_class_majority_voting_and_preservation PASSED [ 53%]
tests/test_tracking.py::test_resolve_track_class_deterministic_tie_breaking PASSED [ 55%]
tests/test_tracking.py::test_resolve_track_class_empty_and_low_confidence PASSED [ 56%]
tests/test_tracking_service.py::test_tracking_run_persists_canonical_tracks PASSED [ 57%]
tests/test_tracking_service.py::test_tracking_bounded_memory_batch_persistence PASSED [ 59%]
tests/test_tracking_service.py::test_tracking_atomic_rollback_on_database_failure PASSED [ 60%]
tests/test_tracking_service.py::test_tracking_rejects_missing_or_incomplete_parent_run PASSED [ 61%]
tests/test_tracking_service.py::test_tracking_windowed_chunk_streaming PASSED [ 63%]
tests/test_tracking_service.py::test_tracking_multichunk_boundary_consistency PASSED [ 64%]
tests/test_trajectories.py::test_compute_ground_point_bottom_center_calculation PASSED [ 65%]
tests/test_trajectories.py::test_compute_ground_point_rejects_bbox_center_and_unsupported_methods PASSED [ 67%]
tests/test_trajectories.py::test_compute_ground_point_rejects_malformed_coordinates PASSED [ 68%]
tests/test_trajectories.py::test_build_trajectories_deterministic_chronological_ordering PASSED [ 69%]
tests/test_trajectories.py::test_build_trajectories_preserves_raw_observations_without_interpolation PASSED [ 71%]
tests/test_trajectories.py::test_build_trajectories_class_consensus_integration PASSED [ 72%]
tests/test_trajectories.py::test_build_trajectories_status_active PASSED [ 73%]
tests/test_trajectories.py::test_build_trajectories_status_complete_exiting_boundary PASSED [ 75%]
tests/test_trajectories.py::test_build_trajectories_status_fragmented_on_prolonged_gap PASSED [ 76%]
tests/test_trajectories.py::test_build_trajectories_status_fragmented_on_interior_termination PASSED [ 77%]
tests/test_trajectories.py::test_build_trajectories_status_invalid_on_malformed_box PASSED [ 78%]
tests/test_trajectories.py::test_build_trajectories_status_invalid_on_duplicate_frame PASSED [ 80%]
tests/test_trajectories.py::test_build_trajectories_status_invalid_on_non_monotonic_timestamp PASSED [ 81%]
tests/test_trajectories.py::test_build_trajectories_empty_and_trail_helpers PASSED [ 82%]
tests/test_visualization.py::test_visualization_config_defaults_and_overrides PASSED [ 84%]
tests/test_visualization.py::test_get_track_color_deterministic PASSED   [ 85%]
tests/test_visualization.py::test_render_frame_annotations_deterministic_output PASSED [ 86%]
tests/test_visualization.py::test_render_frame_annotations_toggles PASSED [ 88%]
tests/test_visualization.py::test_render_frame_annotations_empty_tracks_returns_clean_copy PASSED [ 89%]
tests/test_visualization.py::test_render_frame_annotations_handles_out_of_bounds_and_invalid_boxes PASSED [ 90%]
tests/test_visualization.py::test_build_run_trajectories_service PASSED  [ 92%]
tests/test_visualization.py::test_render_preview_visualization_creates_image PASSED [ 93%]
tests/test_visualization.py::test_render_video_visualization_lineage_and_provenance PASSED [ 94%]
tests/test_visualization.py::test_render_video_visualization_rejects_missing_or_incomplete_parent PASSED [ 96%]
tests/test_visualization.py::test_render_video_visualization_interruption_cleanup PASSED [ 97%]
tests/test_visualization.py::test_render_video_visualization_zero_frames_fails PASSED [ 98%]
tests/test_visualization.py::test_cli_visualize_argument_validation PASSED [100%]

============================= 76 passed in 6.53s ==============================
```

All 76 tests pass on Python 3.12.13, Windows, with zero failures and zero warnings.

---

## 1. Findings Table

| ID | Severity | File:Line | Evidence | Proposed Fix |
|---|---|---|---|---|
| F-01 | **blocker** | `backend/database/schema.sql:236` | `ground_truth_counts.video_segment_id TEXT NOT NULL` references a column with no corresponding `video_segments` table anywhere in the schema. Phase 01 HANDOFF L48 flags this as unresolved. Phase 06 gate (master_prompt L239) requires `video_segments` but no table exists. | Add a `video_segments` table to `schema.sql` before Phase 05 begins, or Phase 06 will fail FK insertion. Phase 05 prompt should explicitly note this as a pre-Phase-06 gate dependency that must be resolved. |
| F-02 | **blocker** | `prompts/phase_05_roi_and_counting_lines.md:15` | Phase 05 prompt says "Support multiple polygonal ROIs" but `backend/database/schema.sql` has no `roi` or `roi_regions` table. The `zones` table (L103-112) stores entry/exit zones, not ROI polygons. There is no defined persistence target for ROI geometry. | Either (a) add an `roi_regions` table to the schema, or (b) clarify in the Phase 5 prompt that ROI polygons are stored in the `zones` table with `zone_type = 'roi'`, or (c) clarify ROIs live only in config YAML. The prompt must be unambiguous on where ROI geometry is persisted. |
| F-03 | **major** | `backend/detection.py:57-58`, `backend/tracking.py:159-160`, `backend/trajectories.py:75` | Ground-point logic `((x1+x2)/2, y2)` is independently implemented in three files. `detection.py` L57-58 (property), `tracking.py` L159-160 (inline), and `trajectories.py` L75 (`compute_ground_point()` with validation). Only `trajectories.py` validates inputs. If the ground-point method changes, two implementations will silently diverge. | Extract `compute_ground_point()` to a shared utility (e.g., `backend/geometry.py`) and call it from all three sites. Phase 05 should import from that utility for counting-line point-in-polygon checks. |
| F-04 | **major** | `docs/handoffs/phase_03/HANDOFF.md:26` vs `configs/default.yaml:46` | Phase 03 HANDOFF documents config key `tracking.batch_size: 500`, but `configs/default.yaml` L46 uses `tracking.chunk_frames: 500`. In `services/tracking.py` L43, the code reads `tracking_cfg.get("batch_size")` falling back to `streaming.frame_batch_size`—this is a *different* concept from `chunk_frames` (L44). `batch_size` controls observation-row flush frequency; `chunk_frames` controls the DB query window. The handoff conflates these. | Update Phase 03 HANDOFF to document both `chunk_frames` (DB query window) and the implicit batch_size (observation flush). Add `batch_size` to `configs/default.yaml` tracking section if it should be configurable. |
| F-05 | **major** | `backend/database/schema.sql:92-101` | `counting_lines` table has `bidirectional INTEGER NOT NULL DEFAULT 0` but no explicit `direction` column. Phase 05 prompt L16 says "direction/bidirectional settings." Where does the line-crossing direction vector (e.g., normal vector or "positive" side) get stored? Presumably `geometry_json`, but this is undocumented in the data dictionary. | Add either a `direction TEXT` column or document in `docs/data_dictionary.md` that direction metadata is embedded in `geometry_json` and specify the schema for that JSON. |
| F-06 | **major** | `backend/database/schema.sql:107` | `zones.zone_type TEXT NOT NULL` has no CHECK constraint. Valid values for Phase 05 (entry, exit, roi, queue) are not enforced at the DB level. Any string could be inserted. | Add `CHECK (zone_type IN ('entry', 'exit', 'roi', 'queue'))` or define the valid vocabulary in the data dictionary and enforce it in application code with tests. |
| F-07 | **major** | `prompts/phase_05_roi_and_counting_lines.md:41` | Completion criteria: "Tests cover geometry validation, reload, entry/exit assignment, line direction, and versioning." This is not measurable—no edge cases, error thresholds, or specific scenarios are named. Compare to Phase 04 prompt L41 which specifies "bottom-centre geometry, ordering, incomplete tracks, overlay toggles, and deterministic rendering inputs." | Add explicit measurable criteria: (a) polygon self-intersection rejection, (b) minimum 3-point polygon, (c) duplicate line_id handling, (d) geometry_sha256 determinism, (e) bidirectional vs unidirectional crossing semantics, (f) zone-approach assignment validation, (g) config version immutability after first use by Phase 06. |
| F-08 | **major** | `prompts/phase_05_roi_and_counting_lines.md:19` | "Render configurations for researcher inspection"—no specification of output format. CLI command? API endpoint? Image file? Overlay on video frame? Phase 04 established both `render_preview_visualization` (image) and `render_video_visualization` (video) patterns. Phase 05 should specify which rendering approach to use. | Specify: (a) CLI subcommand `traffic-vision show-geometry RUN_ID` that renders counting lines and zones overlaid on a video frame preview, (b) output path convention, (c) whether this creates a processing_run record. |
| F-09 | **major** | `prompts/phase_05_roi_and_counting_lines.md:23` | "Phase 04 track/ground-point interfaces and Phase 01 persistence" listed as inputs. But Phase 05 also depends on Phase 02's `detection.frame_stride` for understanding temporal resolution and on Phase 03's `tracking.chunk_frames` for understanding observation density. These are not listed. | Explicitly list: Phase 01 (persistence, config, database), Phase 02 (frame_stride), Phase 03 (track observations in `tracks` table), Phase 04 (trajectory/ground-point interfaces). |
| F-10 | **minor** | `backend/tracking.py:176` | All track observations are persisted with `trajectory_status = "complete"` regardless of actual track state. Phase 04's `build_trajectories()` later reclassifies status. This means the `tracks` table always contains `"complete"` until Phase 04 recomputes status in memory (never writes updated status back to DB). | Document this as intentional: Phase 03 writes a placeholder status; Phase 04 computes the true status in memory during trajectory building. If Phase 05/06 reads `tracks.trajectory_status` directly from DB, it will get incorrect values. Add a note to Phase 05 prompt that trajectory status must be obtained via `build_trajectories()`, not raw DB reads. |
| F-11 | **minor** | `backend/database/schema.sql:28-42` vs `schema.sql:243-251` | `processing_runs.model_version` FK references `model_versions(model_version)`, but `model_versions` is defined 200+ lines later (L243). SQLite tolerates this with `CREATE TABLE IF NOT EXISTS` + deferred FK checks, but individual table creation would fail. | Reorder schema: define `model_versions` before `processing_runs`, and `calibration_runs` before `tracks`. |
| F-12 | **minor** | `backend/services/visualization.py:49-50` | `frame_stride` resolution tries `config.get("trajectories", {}).get("frame_stride")` but the `trajectories` config section in `configs/default.yaml` (L47-51) has no `frame_stride` key. This always evaluates to `None` and falls through to `detection.frame_stride`. Harmless but misleading dead code. | Remove the `trajectories.frame_stride` lookup path or add `frame_stride` to the trajectories config section if it should be independently configurable. |
| F-13 | **minor** | `configs/default.yaml:19` | `gpu_oom_behavior: not_applicable_phase_01` is a placeholder string. Master prompt §22 L237 says Phase 02 gate requires "CPU fallback and GPU OOM behavior." This placeholder was never updated by Phase 02. | Phase 02 should have set this to a meaningful value (e.g., `fallback_to_cpu`). Update during Phase 05 prep or document as deferred. |
| F-14 | **minor** | `prompts/phase_05_roi_and_counting_lines.md:12` | "Every derived/result row must retain run_id" — but `counting_lines` (L92) and `zones` (L103) tables do NOT have `run_id`. They have `video_id` FK only. These are configuration/geometry tables, not result tables, so `run_id` may be intentionally absent. But the prompt boundary section implies run_id is required. | Clarify in the prompt that `counting_lines` and `zones` are geometry-configuration tables (not derived results) and are scoped to `video_id`, not `run_id`. The `config_version` + `geometry_sha256` provide immutability instead. |
| F-15 | **minor** | `backend/database/schema.sql:126` | `crossing_events.line_config_version TEXT NOT NULL` — no FK to `counting_lines.config_version`. This means a crossing event can reference a config version that doesn't exist in counting_lines. | Add `FOREIGN KEY (line_id, line_config_version) REFERENCES counting_lines(line_id, config_version)` or validate at application level with tests. Requires a UNIQUE constraint on `(line_id, config_version)` in `counting_lines` first. |
| F-16 | **minor** | `prompts/phase_05_roi_and_counting_lines.md:26` | "configuration version" mentioned but no specifics on version format (semver? integer? timestamp? hash?). The `counting_lines.config_version TEXT` and `zones.config_version TEXT` columns accept any string. | Specify version format in the prompt or data dictionary. Recommend using `geometry_sha256` as the version identifier for content-addressed immutability. |

---

## 2. Cross-Phase Inconsistencies

### 2.1 Ground-Point Triple Implementation

| Phase | File | Line | Implementation | Validates? |
|---|---|---|---|---|
| 02 | `backend/detection.py` | 57-58 | `(x1+x2)/2`, `y2` (property) | No |
| 03 | `backend/tracking.py` | 159-160 | `float((x1+x2)/2.0)`, `float(y2)` (inline) | No |
| 04 | `backend/trajectories.py` | 39-75 | `compute_ground_point()` with NaN/inf/ordering checks | Yes |

**Risk**: If Phase 05 needs to check whether a ground point falls inside a counting-line zone, it must decide which implementation to use. The unvalidated versions in Phases 02/03 could produce NaN ground points that Phase 04 would later reject as invalid.

### 2.2 Config Key Naming: batch_size vs chunk_frames

| Source | Key Name | Meaning |
|---|---|---|
| `configs/default.yaml:46` | `tracking.chunk_frames: 500` | DB query window size |
| `docs/handoffs/phase_03/HANDOFF.md:26` | `tracking.batch_size: 500` | Observation flush size |
| `backend/services/tracking.py:43` | reads `tracking_cfg.get("batch_size")` | Falls back to `streaming.frame_batch_size` |
| `backend/services/tracking.py:44` | reads `tracking_cfg.get("chunk_frames")` | DB window |

The HANDOFF documents `batch_size` as a tracking config key, but `default.yaml` only has `chunk_frames`. The runtime `batch_size` silently falls back to `streaming.frame_batch_size` (500). These are two different concepts sharing the same default value by coincidence.

### 2.3 trajectory_status Column vs Runtime Status

`backend/tracking.py:176` writes all observations with `trajectory_status = "complete"`. Phase 04's `build_trajectories()` computes the actual status (`active`/`complete`/`fragmented`/`invalid`) in memory but never writes it back to the `tracks` table. Any downstream phase (including Phase 05) that reads `tracks.trajectory_status` from the database will get stale `"complete"` values for every row.

**Impact on Phase 05**: If Phase 05 filters tracks by `trajectory_status` for counting-line crossing checks, it will treat fragmented and invalid tracks as complete.

### 2.4 Phase 01 HANDOFF Flags Missing video_segments

`docs/handoffs/phase_01/HANDOFF.md:48` states: *"Phase 06 will require a deliberate schema/data-dictionary resolution for the documented video_segments contract before it is implemented."*

`master_prompt.md:239` (Phase 06 gate): *"video_segments, ground-truth tables, and frozen acceptance criteria."*

`schema.sql:236`: `ground_truth_counts.video_segment_id TEXT NOT NULL` references a non-existent table.

**Status**: This is acknowledged but unresolved after 4 phases. Phase 05 should resolve this as a pre-Phase-06 gate.

### 2.5 Config Validation Scope Creep

`backend/config.py` validates keys for Phases 01-04 (paths, input, timestamp, streaming, resources, logging, detection, tracking, trajectories, visualization). Phase 05 will need to add validation for a new config section (e.g., `geometry` or `counting_lines`), but `config.py:91` hard-codes the list of required sections. Phase 05 config keys are not pre-stubbed.

### 2.6 API Skeleton Not Extended Beyond Phase 01

`backend/app.py` exposes only `/health` and `/status`. Phases 02-04 added CLI commands but no API endpoints. Phase 05 prompt says "Render configurations for researcher inspection" which could imply a REST endpoint, but the app has no pattern for phase-specific endpoints yet.

---

## 3. Phase 5 Prompt Improvements Needed

### 3.1 Ambiguities Requiring Resolution

| # | Ambiguity | Where in Prompt | Impact |
|---|---|---|---|
| A1 | Where are polygonal ROIs persisted? (DB table? config YAML? `zones` table with `zone_type='roi'`?) | L15 "Support multiple polygonal ROIs" | Implementer will guess; could create an ad-hoc table or stuff ROIs into zones. |
| A2 | What is the rendering output format for "Render configurations for researcher inspection"? | L19 | Could produce CLI text output, JSON, an image overlay, or an API response. |
| A3 | How is line-crossing direction represented? (Normal vector? Named direction? In geometry_json?) | L16 "direction/bidirectional settings" | No schema column for direction. Implementer must decide JSON sub-schema. |
| A4 | What constitutes a valid polygon? (Minimum vertices? Self-intersection? Clockwise/CCW?) | L15, L18 "Validate geometry" | Without explicit rules, validation may be trivially permissive. |
| A5 | Is geometry_sha256 computed over geometry_json only, or over geometry_json + approach + name? | L18 "persist versioned configuration" | Determines whether renaming an approach creates a new version. |
| A6 | Do counting_lines/zones carry run_id or only video_id? | L12 boundary says "retain run_id" | Schema has video_id only. Prompt contradicts schema for these tables. |
| A7 | How does Phase 05 interact with the existing `detection.roi_crop` config from Phase 02? | L15 "multiple polygonal ROIs" | Phase 02 already has a rectangular `roi_crop` in config. Phase 05's ROI could conflict or supersede it. |

### 3.2 Missing Acceptance Criteria

The Phase 05 completion criteria (L41-42) state only: *"Tests cover geometry validation, reload, entry/exit assignment, line direction, and versioning."*

**Missing measurable criteria:**

1. **Polygon validation**: Minimum 3 non-collinear vertices; rejection of self-intersecting polygons; rejection of zero-area polygons.
2. **Counting-line validation**: Line must have exactly 2 endpoints; endpoints must be distinct; line must be inside the video frame.
3. **geometry_sha256 determinism**: Same geometry JSON must always produce the same hash; different geometries must produce different hashes.
4. **Config version immutability**: Once a config_version is referenced by a `crossing_event` in Phase 06, modifying the geometry must create a new version, not update in place.
5. **Bidirectional semantics**: Define what "positive" and "negative" crossing directions mean relative to the line geometry.
6. **Entry/exit zone coverage**: Each approach must have at least one entry zone; zones must not overlap across approaches (or document that overlapping is acceptable).
7. **Reload/idempotency**: Loading the same geometry config twice must not create duplicate rows.
8. **CLI or API contract**: Specify the exact interface for configuring geometry.
9. **Integration with Phase 04 trajectories**: A test should verify that a trajectory's ground points can be tested against a configured counting line.

### 3.3 Missing Dependencies and Pre-Conditions

The Phase 05 prompt should explicitly state:

1. **Pre-Phase-06 gate**: `video_segments` table must be defined before Phase 06 (master_prompt L239). Phase 05 should at minimum flag this; ideally add the table.
2. **Phase 02 `detection.roi_crop` relationship**: Clarify whether Phase 05's polygonal ROIs replace, augment, or are independent of the rectangular ROI crop.
3. **Phase 04 `build_trajectories()` dependency**: Phase 05 must use `build_trajectories()` (not raw `tracks` table reads) to get correct trajectory status, due to the stale `trajectory_status` column issue (see §2.3).
4. **Geometry JSON sub-schema**: Define the expected structure of `geometry_json` for both counting_lines and zones (e.g., `{"points": [[x1,y1], [x2,y2], ...]}` for lines, `{"vertices": [[x1,y1], ...]}` for polygons).

### 3.4 Recommended Prompt Additions

```markdown
## Pre-Phase-05 gate
- Resolve the `video_segments` table absence flagged in Phase 01 HANDOFF.md:48.
- Confirm whether `zones.zone_type` should have a CHECK constraint.
- Document the geometry_json sub-schema for counting_lines and zones in
  docs/data_dictionary.md before implementation.

## Geometry JSON contract
counting_lines.geometry_json must contain:
  {"endpoints": [[x1,y1], [x2,y2]], "direction_vector": [dx, dy]}
zones.geometry_json must contain:
  {"vertices": [[x1,y1], [x2,y2], ..., [xn,yn]]}

## Relationship to Phase 02 roi_crop
Phase 05 polygonal ROIs are for counting/analytics zones, not for
detection preprocessing. detection.roi_crop remains a Phase 02 concern.

## Completion criteria (enhanced)
- Polygon with < 3 vertices is rejected.
- Self-intersecting polygon is rejected.
- Counting line with coincident endpoints is rejected.
- geometry_sha256 is deterministic (same JSON → same hash).
- Reloading identical geometry does not create duplicate DB rows.
- Entry/exit zone assignment is validated against declared approaches.
- Rendering overlay shows configured lines/zones on a video frame.
- Integration test: Phase 04 trajectory ground points can be tested
  against a configured counting line using point-on-line-side check.
```

---

## 4. Test Gaps

### 4.1 Missing Tests for Existing Implementation (Phases 1–4)

| Gap ID | Phase | Description | Risk |
|---|---|---|---|
| TG-01 | 01 | No test for VFR video beyond the `TimestampAudit` flag. No test confirms downstream phases correctly refuse to synthesize timestamps from nominal FPS on VFR input. | Medium: VFR handling claimed but untested end-to-end. |
| TG-02 | 02 | No test for GPU OOM fallback. `resources.gpu_oom_behavior` is a placeholder string `"not_applicable_phase_01"`. Phase 02 prompt requires CPU fallback. | Low: CPU-only testing is fine for now, but the config placeholder is misleading. |
| TG-03 | 02 | No test loads actual YOLO weights. All detection tests use a mock `Detector` protocol implementation. | Low: Intentional for CI, but means model-loading errors won't be caught until manual integration. |
| TG-04 | 03 | No test for `tracking.chunk_frames` vs `batch_size` interaction. The two config keys control different things but share the same default. | Medium: Could cause subtle memory/performance issues with non-default configs. |
| TG-05 | 03 | `trajectory_status = "complete"` is hardcoded for all DB rows (tracking.py:176). No test verifies that downstream code does NOT rely on this DB column value. | High: Phase 05/06 could read stale status from DB. |
| TG-06 | 04 | `services/visualization.py:49-50` dead-code path (`trajectories.frame_stride`) is never exercised by any test. | Low: Harmless dead code but indicates incomplete config design. |
| TG-07 | 04 | No test for actual video file rendering with cv2.VideoWriter. Tests mock the video path. If OpenCV's mp4v codec is unavailable on a system, rendering silently fails. | Medium: Platform-dependent failure mode. |
| TG-08 | 01-04 | No end-to-end integration test that chains Phase 01 → 02 → 03 → 04 in a single test. Individual phase tests exist but cross-phase data flow (e.g., detection ground_x flowing through tracking to trajectory) is untested. | Medium: Cross-phase data corruption could go undetected. |
| TG-09 | 01 | No test for concurrent database writes (multiple ingestion runs in parallel). `PRAGMA busy_timeout = 5000` is set but never stress-tested. | Low: SQLite single-writer limitation is well-understood; unlikely for offline research pipeline. |
| TG-10 | 01 | No negative test for schema migration (e.g., what happens when a column is added to schema.sql). `SchemaMigrationRequired` is raised but recovery path is untested. | Low: Schema stability is expected within a phase; migrations would be manual. |

### 4.2 Tests Needed for Phase 5

| Test ID | Description |
|---|---|
| TP5-01 | Polygon with 3 vertices creates a valid zone; 2 vertices rejected. |
| TP5-02 | Self-intersecting polygon rejected. |
| TP5-03 | Counting line with 2 distinct endpoints accepted; coincident endpoints rejected. |
| TP5-04 | `geometry_sha256` is deterministic: same geometry_json → same hash, different JSON → different hash. |
| TP5-05 | Inserting the same geometry twice (same line_id + config_version) is idempotent or rejected. |
| TP5-06 | Entry zone and exit zone assigned to an approach; zone without approach rejected. |
| TP5-07 | Bidirectional line allows crossing in both directions; unidirectional rejects reverse. |
| TP5-08 | Zone type validation: only valid zone_type values accepted. |
| TP5-09 | Geometry rendering produces a non-empty image with lines/zones overlaid. |
| TP5-10 | Integration: a trajectory's ground_x/ground_y points can be checked against a counting line (point-on-which-side-of-line). |
| TP5-11 | Config version immutability: attempting to modify geometry for an existing config_version raises an error. |
| TP5-12 | Multiple ROIs per video accepted; ROI outside frame boundaries rejected. |

---

## 5. Phase-by-Phase Audit Summary

### Phase 01: Video Input and Foundational Scaffolding ✅

**Prompt compliance**: Full. All scope items implemented.
- Video ingestion with SHA-256 ✅
- Decoder PTS timestamps via PyAV ✅
- VFR detection and flagging ✅
- Config loading with deterministic hashing ✅
- Schema bootstrap with version tracking ✅
- API skeleton (`/health`, `/status`) ✅
- Streaming frame iteration ✅
- Parent run_id support ✅

**Issues**: None blocking. `gpu_oom_behavior` placeholder (F-13) is minor.

### Phase 02: YOLO Detection ✅

**Prompt compliance**: Full. All scope items implemented.
- Configurable YOLO detector adapter ✅
- ROI crop with offset preservation ✅
- Tiled inference with deterministic merge ✅
- Explicit class mapping (no COCO assumptions) ✅
- Detection separated from tracking ✅
- Full geometry persisted with ground point ✅

**Issues**: Ground point computed without validation (F-03). GPU OOM placeholder not updated (F-13).

### Phase 03: ByteTrack Integration ✅

**Prompt compliance**: Full. All scope items implemented.
- Direct `BYTETracker` usage (not `model.track()`) ✅
- Cadence-to-frames conversion ✅
- Track lifecycle management ✅
- ID-switch instrumentation (explicit `None` without ground truth) ✅
- Confidence-weighted class voting ✅
- Bounded-memory batch persistence ✅

**Issues**: Handoff documents wrong config key name (F-04). Hardcoded `trajectory_status = "complete"` (F-10).

### Phase 04: Trajectories and Visualization ✅

**Prompt compliance**: Full. All scope items implemented.
- Ordered trajectory histories by run_id/track_id ✅
- Bottom-centre ground point with validation ✅
- Bbox centre explicitly rejected ✅
- Trajectory status classification (active/complete/fragmented/invalid) ✅
- Gap-aware trail segmentation ✅
- Overlay toggles ✅
- Video/preview rendering with provenance ✅
- CLI command ✅

**Issues**: Dead code path for `trajectories.frame_stride` config (F-12). Status computed in memory only, not written back to DB (F-10, cross-phase).

### Phase 05: Prompt Readiness ⚠️ Conditional

**Readiness verdict**: NOT READY without fixes to F-01, F-02, F-05, F-06, F-07, F-08.

| Criterion | Status |
|---|---|
| Schema tables exist for all prompt scope items | ❌ No ROI table; zone_type unconstrained |
| Dependencies explicitly listed | ⚠️ Missing Phase 02/03 dependencies |
| Acceptance criteria measurable | ❌ Vague; no edge cases specified |
| API/CLI interface specified | ❌ "Render configurations" unspecified |
| Data dictionary covers Phase 05 fields | ⚠️ direction, geometry_json sub-schema missing |
| Pre-Phase-06 gates addressed | ❌ video_segments still missing |
| Cross-phase interfaces documented | ⚠️ trajectory_status DB vs runtime issue undocumented |

---

## 6. Files Inspected

| File | Lines | Role |
|---|---|---|
| `prompts/master_prompt.md` | 262 | Authority |
| `prompts/review_checklist.md` | 57 | Checklist |
| `prompts/audit_prompt_claude_opus.md` | 188 | Audit instructions |
| `prompts/phase_01_video_input_and_playback.md` | 59 | Phase 01 prompt |
| `prompts/phase_02_yolo_detection.md` | 49 | Phase 02 prompt |
| `prompts/phase_03_bytetrack_integration.md` | 48 | Phase 03 prompt |
| `prompts/phase_04_trajectories_and_visualization.md` | 48 | Phase 04 prompt |
| `prompts/phase_05_roi_and_counting_lines.md` | 49 | Phase 05 prompt |
| `backend/database/schema.sql` | 262 | Schema source of truth |
| `docs/data_dictionary.md` | 76 | Data contract |
| `configs/default.yaml` | 64 | Default configuration |
| `backend/app.py` | 23 | API skeleton |
| `backend/cli.py` | 132 | CLI entry point |
| `backend/config.py` | 190 | Config loader + validator |
| `backend/media.py` | 166 | Video inspection + streaming |
| `backend/detection.py` | 184 | Detection primitives |
| `backend/tracking.py` | 262 | Tracking primitives |
| `backend/trajectories.py` | 481 | Trajectory builder |
| `backend/visualization.py` | 253 | Rendering engine |
| `backend/database/connection.py` | 77 | DB bootstrap |
| `backend/database/repository.py` | 179 | DB operations |
| `backend/services/ingestion.py` | 138 | Phase 01 orchestration |
| `backend/services/detection.py` | 77 | Phase 02 orchestration |
| `backend/services/tracking.py` | 221 | Phase 03 orchestration |
| `backend/services/visualization.py` | 310 | Phase 04 orchestration |
| `docs/handoffs/phase_01/HANDOFF.md` | 49 | Phase 01 handoff |
| `docs/handoffs/phase_02/HANDOFF.md` | 34 | Phase 02 handoff |
| `docs/handoffs/phase_03/HANDOFF.md` | 87 | Phase 03 handoff |
| `docs/handoffs/phase_04/HANDOFF.md` | 172 | Phase 04 handoff |
| `tests/test_app.py` | 2 tests | API tests |
| `tests/test_config.py` | 2 tests | Config tests |
| `tests/test_database.py` | 3 tests | DB tests |
| `tests/test_detection.py` | 4 tests | Detection tests |
| `tests/test_detection_service.py` | 1 test | Detection service test |
| `tests/test_ingestion.py` | 2 tests | Ingestion tests |
| `tests/test_media.py` | 2 tests | Media tests |
| `tests/test_tracking.py` | 9 tests | Tracking tests |
| `tests/test_tracking_service.py` | 6 tests | Tracking service tests |
| `tests/test_trajectories.py` | 14 tests | Trajectory tests |
| `tests/test_visualization.py` | 13 tests | Visualization tests |
| `tests/test_phase_04_audit.py` | 18 tests | Phase 04 audit tests |
| `pyproject.toml` | — | Build config |
