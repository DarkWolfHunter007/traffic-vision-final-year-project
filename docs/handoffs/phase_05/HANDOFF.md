# Phase 05 Handoff — ROI, Entry/Exit Zones, and Counting-Line Configuration

## 1. Delivered Interfaces and Modules

### Pure Geometry Primitives (`backend.geometry`)
- `validate_polygon(vertices, frame_width=None, frame_height=None)`: Validates 2D planar polygons. Enforces $\ge 3$ distinct vertices, finiteness of coordinates, frame boundaries $[0, width] \times [0, height]$, non-zero area via Shoelace formula, and absence of self-intersecting or self-touching edges. Normalizes closed polygons (stripping identical closing endpoint).
- `polygon_area(vertices)`: Pure implementation of the Shoelace planar area calculation.
- `segments_intersect(a, b, c, d, eps=1e-9)`: Robust 2D segment-segment intersection test using orientation cross-products (`_ccw`) and bounding-box collinear containment tests (`_on_segment`).
- `is_polygon_self_intersecting(vertices, eps=1e-9)`: Checks all non-adjacent edge pairs of a closed polygon for intersection.
- `validate_counting_line(endpoints, direction_vector=None, bidirectional=False, frame_width=None, frame_height=None)`: Validates counting-line geometry. Enforces exactly 2 distinct endpoints (rejecting coincident points), finiteness, and frame bounds. Enforces that bidirectional lines have `direction_vector = None` and unidirectional lines require a finite, non-zero direction vector $[dx, dy]$.
- `validate_zone(vertices, zone_type, approach=None, declared_approaches=None, frame_width=None, frame_height=None)`: Validates zone attributes and geometry. Enforces that `zone_type` is in `{'entry', 'exit', 'roi', 'queue'}`; enforces that `entry` and `exit` zones are assigned to a declared approach; validates approach references against `declared_approaches`.
- `compute_geometry_sha256(geometry, approach, name)`: Computes a deterministic SHA-256 hash over canonical sorted-key JSON (`{"approach": approach, "geometry": geometry, "name": name}`).
- `compute_config_version(geometry_sha256)`: Returns the first 12 lowercase hexadecimal characters of `geometry_sha256`.
- `point_line_cross_product(point, line_start, line_end)`: Computes 2D vector cross product $(x_2 - x_1)(y - y_1) - (y_2 - y_1)(x - x_1)$.
- `point_side_of_line(point, line_start, line_end, eps=1e-9)` (and aliases `side_of_line`, `point_line_side`): Returns `+1` (left/positive side), `-1` (right/negative side), or `0` (collinear within tolerance).

### Geometry Configuration Service (`backend.services.geometry_config`)
- `load_geometry_config(video_id, config_path_or_dict, config=None, repository_root=None, connection=None)`: Loads and validates YAML/JSON geometry configuration files or dictionaries. Persists configuration into canonical `counting_lines` and `zones` tables. Reloading identical configuration is idempotent (no-op, preserves existing rows). Modifying geometry for an existing line/zone ID is rejected to enforce immutability; changed geometry yields a new configuration version.
- `fetch_geometry_for_video(connection, video_id)`: Fetches all configured counting lines and zones for a given `video_id`.
- `render_geometry_preview(video_id, output_path, frame_number=0, config=None, repository_root=None, connection=None)`: Decodes a single preview frame from the source video, overlays semi-transparent zones and directed counting lines, and writes the preview image to disk. Creates NO `processing_run` record.

### Visualization Engine Extension (`backend.visualization`)
- `render_geometry_overlay(image, lines, zones)`: Renders polygonal zones with distinct colors by zone type (`entry`: green, `exit`: red, `roi`: cyan, `queue`: violet) with semi-transparent fill and solid boundary, along with counting lines (gold) featuring circle endpoints, direction vector arrows (orange) for unidirectional lines, and text labels.

### Repository Operations (`backend.database.repository`)
- `insert_counting_line(connection, line)`: Inserts a row into `counting_lines`.
- `insert_zone(connection, zone)`: Inserts a row into `zones`.
- `fetch_counting_lines_for_video(connection, video_id)`: Retrieves counting lines ordered by `line_id ASC`.
- `fetch_zones_for_video(connection, video_id)`: Retrieves zones ordered by `zone_id ASC`.
- `fetch_counting_line_by_id(connection, line_id)`: Fetches a single counting line by primary key.
- `fetch_zone_by_id(connection, zone_id)`: Fetches a single zone by primary key.

### CLI Commands (`backend.cli`)
- `traffic-vision load-geometry VIDEO_ID CONFIG_PATH [--config CONFIG]`: Loads and validates geometry from YAML/JSON file into `counting_lines` and `zones` tables.
- `traffic-vision show-geometry VIDEO_ID --output OUTPUT_IMAGE [--frame FRAME_NUMBER] [--config CONFIG]`: Overlays lines and zones on video preview frame and writes image file without creating a `processing_run`.

---

## 2. Changed and Created Files

| File | Status | Description |
|---|---|---|
| `backend/geometry.py` | Modified | Added polygon validation, counting-line validation, zone validation, SHA-256 hashing, config version derivation, and point-line side helpers. Preserved `compute_ground_point`. |
| `backend/database/repository.py` | Modified | Added persistence and retrieval functions for `counting_lines` and `zones`. |
| `backend/visualization.py` | Modified | Added `render_geometry_overlay` for rendering zones, counting lines, direction arrows, and labels onto image frames. |
| `backend/services/geometry_config.py` | Created | Service orchestrating validation, idempotent immutable persistence, and preview rendering. |
| `backend/cli.py` | Modified | Added `load-geometry` and `show-geometry` CLI subparsers and execution branches. |
| `configs/pattom_geometry.yaml` | Created | Example YAML geometry configuration defining approaches, counting lines, entry/exit zones, core ROI, and queue area for Pattom Intersection. |
| `tests/test_geometry.py` | Created | Focused unit tests for pure geometry functions covering TP5-01, TP5-02, TP5-03, TP5-04, TP5-07, TP5-08, and side-of-line mathematics. |
| `tests/test_geometry_service.py` | Created | Service and CLI integration tests with synthetic fixtures covering TP5-05, TP5-06, TP5-09, TP5-10, TP5-11, TP5-12. |
| `docs/handoffs/phase_05/HANDOFF.md` | Created | This handoff documentation. |

---

## 3. Schema Usage and Invariants

No schema changes were made. Canonical tables in `backend/database/schema.sql` are used strictly as designed:
- **`counting_lines`**:
  - `line_id`: Stable text primary key.
  - `video_id`: Foreign key to `videos(video_id)`.
  - `name`: Human-readable identifier.
  - `approach`: Declared approach name or NULL.
  - `geometry_json`: Canonical JSON string `{"direction_vector": [dx, dy] | null, "endpoints": [[x1, y1], [x2, y2]]}`.
  - `bidirectional`: Integer boolean (0 or 1).
  - `config_version`: 12-character hex prefix of `geometry_sha256`.
  - `geometry_sha256`: Deterministic SHA-256 hex digest over canonical sorted-key JSON `{"approach": ..., "geometry": ..., "name": ...}`.
- **`zones`**:
  - `zone_id`: Stable text primary key.
  - `video_id`: Foreign key to `videos(video_id)`.
  - `name`: Human-readable identifier.
  - `zone_type`: One of `'entry'`, `'exit'`, `'roi'`, `'queue'`.
  - `approach`: Declared approach name for entry/exit; optional for roi/queue.
  - `geometry_json`: Canonical JSON string `{"vertices": [[x1, y1], ...]}`.
  - `config_version`: 12-character hex prefix of `geometry_sha256`.
  - `geometry_sha256`: Deterministic SHA-256 hex digest over canonical sorted-key JSON `{"approach": ..., "geometry": ..., "name": ...}`.

---

## 4. Configuration Schema and Example (`configs/pattom_geometry.yaml`)

```yaml
approaches:
  - north
  - south
  - east
  - west

counting_lines:
  - line_id: line_north_entry
    name: "North Entry Counting Line"
    approach: north
    endpoints:
      - [300.0, 400.0]
      - [500.0, 400.0]
    direction_vector: [0.0, 1.0]
    bidirectional: false

  - line_id: line_east_bidirectional
    name: "East Approach Boundary Line"
    approach: east
    endpoints:
      - [800.0, 400.0]
      - [800.0, 700.0]
    direction_vector: null
    bidirectional: true

zones:
  - zone_id: zone_north_entry
    name: "North Approach Entry Zone"
    zone_type: entry
    approach: north
    vertices:
      - [250.0, 200.0]
      - [550.0, 200.0]
      - [550.0, 390.0]
      - [250.0, 390.0]

  - zone_id: zone_intersection_roi
    name: "Intersection Core ROI"
    zone_type: roi
    approach: null
    vertices:
      - [200.0, 350.0]
      - [850.0, 350.0]
      - [850.0, 850.0]
      - [200.0, 850.0]
```

---

## 5. Raw Test Results

Running `uv run pytest -v`:

```text
============================= test session starts =============================
platform win32 -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0 -- D:\Work\Personal\traffic-vision-final-year-project\.venv\Scripts\python.exe
cachedir: .pytest_cache
rootdir: D:\Work\Personal\traffic-vision-final-year-project
configfile: pyproject.toml
plugins: anyio-4.15.1
collecting ... collected 90 items

tests/test_app.py::test_app_health PASSED                                [  1%]
tests/test_config.py::test_load_config_deep_merges_and_hashes_deterministically PASSED [  2%]
tests/test_config.py::test_load_config_rejects_missing_required_sections PASSED [  3%]
tests/test_database.py::test_schema_declares_canonical_entities PASSED  [  4%]
tests/test_database.py::test_bootstrap_enables_foreign_keys_on_every_connection PASSED [  5%]
tests/test_database.py::test_bootstrap_is_idempotent PASSED              [  6%]
tests/test_database.py::test_bootstrap_rejects_a_database_with_an_unknown_schema PASSED [  7%]
tests/test_detection.py::test_mapping_requires_explicit_project_class PASSED [  8%]
tests/test_detection.py::test_tile_generation_covers_frame_edges_deterministically PASSED [ 10%]
tests/test_detection.py::test_tile_merge_is_class_aware_and_deterministic PASSED [ 11%]
tests/test_detection.py::test_roi_crop_validates_and_preserves_offsets PASSED [ 12%]
tests/test_detection_service.py::test_detection_run_persists_only_canonical_detections PASSED [ 13%]
tests/test_geometry.py::test_tp5_01_polygon_vertex_count_acceptance_and_rejection PASSED [ 14%]
tests/test_geometry.py::test_tp5_02_polygon_self_intersection_and_zero_area_rejection PASSED [ 15%]
tests/test_geometry.py::test_tp5_03_counting_line_endpoint_validation PASSED [ 16%]
tests/test_geometry.py::test_tp5_04_geometry_sha256_determinism_and_config_version PASSED [ 17%]
tests/test_geometry.py::test_tp5_07_bidirectional_and_unidirectional_line_rules PASSED [ 18%]
tests/test_geometry.py::test_tp5_08_zone_type_application_validation PASSED [ 20%]
tests/test_geometry.py::test_side_of_line_helpers PASSED                 [ 21%]
tests/test_geometry_service.py::test_tp5_05_idempotent_reload_preserves_existing_rows PASSED [ 22%]
tests/test_geometry_service.py::test_tp5_06_entry_exit_declared_approach_validation PASSED [ 23%]
tests/test_geometry_service.py::test_tp5_09_show_geometry_rendering_no_processing_run PASSED [ 24%]
tests/test_geometry_service.py::test_tp5_10_trajectory_ground_points_against_counting_line_integration PASSED [ 25%]
tests/test_geometry_service.py::test_tp5_11_config_version_immutability PASSED [ 26%]
tests/test_geometry_service.py::test_tp5_12_multiple_rois_and_out_of_bounds_rejection PASSED [ 27%]
tests/test_geometry_service.py::test_cli_load_geometry_and_show_geometry PASSED [ 28%]
tests/test_ingestion.py::test_ingestion_persists_metadata_run_and_decoder_pts PASSED [ 30%]
tests/test_ingestion.py::test_preview_decodes_one_requested_frame_sequentially PASSED [ 31%]
tests/test_media.py::test_timestamp_audit_marks_variable_cadence PASSED  [ 32%]
tests/test_media.py::test_timestamp_audit_marks_missing_or_non_monotonic_pts PASSED [ 33%]
tests/test_phase_04_audit.py::test_audit_cross_run_track_id_collision PASSED [ 34%]
tests/test_phase_04_audit.py::test_audit_active_status_precedence_over_internal_gaps PASSED [ 35%]
tests/test_phase_04_audit.py::test_audit_motion_trail_connects_across_unobserved_gaps PASSED [ 36%]
tests/test_phase_04_audit.py::test_audit_motion_trail_short_continuous_gap_renders_trail PASSED [ 37%]
tests/test_phase_04_audit.py::test_audit_motion_trail_intentional_frame_stride PASSED [ 38%]
tests/test_phase_04_audit.py::test_audit_motion_trail_segments_around_gap PASSED [ 40%]
tests/test_phase_04_audit.py::test_audit_zero_area_bounding_box PASSED   [ 41%]
tests/test_phase_04_audit.py::test_audit_stride_aware_gap_accounting PASSED [ 42%]
tests/test_phase_04_audit.py::test_audit_corrupt_stored_ground_coordinates_rejected PASSED [ 43%]
tests/test_phase_04_audit.py::test_audit_negative_and_nonfinite_timestamps_rejected PASSED [ 44%]
tests/test_phase_04_audit.py::test_audit_interior_termination_semantics PASSED [ 45%]
tests/test_phase_04_audit.py::test_audit_visualization_frame_range_validation PASSED [ 46%]
tests/test_phase_04_audit.py::test_audit_one_frame_range_preview_and_video PASSED [ 47%]
tests/test_phase_04_audit.py::test_audit_trail_gap_exact_boundary PASSED [ 48%]
tests/test_phase_04_audit.py::test_audit_trail_gap_large_frame_stride_splits_all_samples PASSED [ 50%]
tests/test_phase_04_audit.py::test_audit_ground_point_tolerance PASSED   [ 51%]
tests/test_phase_04_audit.py::test_audit_interior_termination_boundary_margin PASSED [ 52%]
tests/test_phase_04_audit.py::test_audit_stride_off_grid_gaps_current_behavior PASSED [ 53%]
tests/test_tracking.py::test_cadence_to_frames_conversion PASSED         [ 54%]
tests/test_tracking.py::test_detection_batch_properties_and_slicing PASSED [ 55%]
tests/test_tracking.py::test_persistent_id_association_across_frames PASSED [ 56%]
tests/test_tracking.py::test_empty_frame_handling PASSED                 [ 57%]
tests/test_tracking.py::test_missed_detection_reconnection_within_buffer PASSED [ 58%]
tests/test_evaluate_id_switches_known_switch_and_no_switch PASSED       [ 60%]
tests/test_resolve_track_class_majority_voting_and_preservation PASSED   [ 61%]
tests/test_resolve_track_class_deterministic_tie_breaking PASSED         [ 62%]
tests/test_resolve_track_class_empty_and_low_confidence PASSED           [ 63%]
tests/test_tracking_service.py::test_tracking_run_persists_canonical_tracks PASSED [ 64%]
tests/test_tracking_service.py::test_tracking_bounded_memory_batch_persistence PASSED [ 65%]
tests/test_tracking_service.py::test_tracking_atomic_rollback_on_database_failure PASSED [ 66%]
tests/test_tracking_service.py::test_tracking_rejects_missing_or_incomplete_parent_run PASSED [ 67%]
tests/test_tracking_service.py::test_tracking_windowed_chunk_streaming PASSED [ 68%]
tests/test_tracking_service.py::test_tracking_multichunk_boundary_consistency PASSED [ 70%]
tests/test_trajectories.py::test_compute_ground_point_bottom_center_calculation PASSED [ 71%]
tests/test_trajectories.py::test_compute_ground_point_rejects_bbox_center_and_unsupported_methods PASSED [ 72%]
tests/test_trajectories.py::test_compute_ground_point_rejects_malformed_coordinates PASSED [ 73%]
tests/test_trajectories.py::test_build_trajectories_deterministic_chronological_ordering PASSED [ 74%]
tests/test_trajectories.py::test_build_trajectories_preserves_raw_observations_without_interpolation PASSED [ 75%]
tests/test_trajectories.py::test_build_trajectories_class_consensus_integration PASSED [ 76%]
tests/test_trajectories.py::test_build_trajectories_status_active PASSED [ 77%]
tests/test_trajectories.py::test_build_trajectories_status_complete_exiting_boundary PASSED [ 78%]
tests/test_trajectories.py::test_build_trajectories_status_fragmented_on_prolonged_gap PASSED [ 80%]
tests/test_trajectories.py::test_build_trajectories_status_fragmented_on_interior_termination PASSED [ 81%]
tests/test_trajectories.py::test_build_trajectories_status_invalid_on_malformed_box PASSED [ 82%]
tests/test_trajectories.py::test_build_trajectories_status_invalid_on_duplicate_frame PASSED [ 83%]
tests/test_trajectories.py::test_build_trajectories_status_invalid_on_non_monotonic_timestamp PASSED [ 84%]
tests/test_trajectories.py::test_build_trajectories_empty_and_trail_helpers PASSED [ 85%]
tests/test_visualization.py::test_visualization_config_defaults_and_overrides PASSED [ 86%]
tests/test_visualization.py::test_get_track_color_deterministic PASSED   [ 87%]
tests/test_visualization.py::test_render_frame_annotations_deterministic_output PASSED [ 88%]
tests/test_visualization.py::test_render_frame_annotations_toggles PASSED [ 90%]
tests/test_visualization.py::test_render_frame_annotations_empty_tracks_returns_clean_copy PASSED [ 91%]
tests/test_visualization.py::test_render_frame_annotations_handles_out_of_bounds_and_invalid_boxes PASSED [ 92%]
tests/test_visualization.py::test_build_run_trajectories_service PASSED  [ 93%]
tests/test_visualization.py::test_render_preview_visualization_creates_image PASSED [ 94%]
tests/test_visualization.py::test_render_video_visualization_lineage_and_provenance PASSED [ 95%]
tests/test_visualization.py::test_render_video_visualization_rejects_missing_or_incomplete_parent PASSED [ 96%]
tests/test_visualization.py::test_render_video_visualization_interruption_cleanup PASSED [ 97%]
tests/test_visualization.py::test_render_video_visualization_zero_frames_fails PASSED [ 98%]
tests/test_cli_visualize_argument_validation PASSED                       [100%]

============================= 90 passed in 8.03s ==============================
```

Running `uv run pytest -q`:
```text
90 passed in 8.08s
```

---

## 6. Assumptions and Limitations

1. **Pixel-Space Float Coordinates**: All geometry vertex and endpoint coordinates are in pixel space bounded by the source video frame dimensions $[0, width] \times [0, height]$. Physical metric projection is deferred to Phase 07 (calibration).
2. **Simple Polygons**: Zones and ROIs must be non-self-intersecting simple polygons. Concave and convex polygons are both supported, but self-crossing polygons (e.g. figure-eights or self-intersecting stars) and zero-area polygons are rejected.
3. **Immutability Model**: Rows in `counting_lines` and `zones` are immutable. If geometry, approach, or name changes, a new configuration version is derived and must be registered with a distinct identifier; overwriting an existing line or zone record with altered geometry is prohibited.
4. **Scope Exclusions**: No crossing events, vehicle counting, movement derivation (left/through/right), speed estimation, or queue metrics are implemented in this phase.

---

## 7. Dependencies for Phase 06

- Phase 06 owns crossing events, vehicle counting, movement derivation (entry-to-exit evidence), ground-truth sets, and 15-minute volume bins.
- Phase 06 must reference `counting_lines.line_id` and `counting_lines.config_version` when recording crossing events in `crossing_events`.
- Phase 06 must consume trajectories assembled by Phase 04 `build_trajectories()` and evaluate line crossing using the pure helper `point_side_of_line` from `backend.geometry`.

---

## 8. Independent Review Notice

In accordance with prompt instructions, this implementation model has run all phase tests and reported raw test results, but does not perform the final checks or declare the phase accepted. Final verification and review are reserved for independent review subagents.
