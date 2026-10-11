# Phase 04 Independent Validation Report — Trajectories & Visualization

**Auditor Role:** Senior Computer-Vision Engineer, Python QA Engineer, and Civil Engineering Research-Methodology Auditor  
**Repository:** Traffic Vision (Pattom Intersection, Thiruvananthapuram)  
**Branch:** `antigravity/v1.0.2`  
**Inspected Commit:** `364ce8032f1464e49ddfdb452a91fa4d7fc85ddb` (`feat: implement Phase 04 trajectories and visualization`)  
**Base Commit:** `7556381ecb8357bf8b3a5a27738cc01a8a2f218a` (`feat: complete Phase 03 ByteTrack integration and remediation`)  
**Status Verdict:** **CONDITIONAL PASS**

---

## 1. Executive Summary & Verdict

Phase 04 delivers the core data structures and visualization pipelines for vehicle trajectories derived from Phase 03 ByteTrack observations. The implementation strictly adheres to the canonical data contract (`docs/data_dictionary.md` and `backend/database/schema.sql`):
1. **Bottom-Centre Road Projection**: Bounding-box bottom-centre `((x1 + x2)/2, y2)` is computed as the road-plane contact point, and bounding-box centre coordinates are strictly rejected.
2. **Preservation of Raw Observations**: No intermediate points are interpolated or fabricated into trajectory histories. Raw per-frame bounding boxes and class labels remain unaltered.
3. **Deterministic Class Consensus**: Reuses Phase 03 confidence-weighted voting (`resolve_track_class`) to assign stable track-level vehicle categories.
4. **Deterministic Visualization**: Provides pure, repeatable annotation with independent toggles for bounding boxes, class labels, confidence scores, track IDs, motion trails, and ground points.
5. **Lineage and Failure Recovery**: Registers child `processing_runs` with parent tracking run links, atomic file replacement (`.tmp.mp4` -> `.mp4`), and automatic cleanup on error.

**Verdict: CONDITIONAL PASS.**  
The implementation is technically sound, regression-tested (58 passing tests including 4 independent audit probes), and safe for Phase 05 integration. However, acceptance is conditional upon documenting that:
- Motion trail polylines currently connect across unobserved frame gaps.
- Trajectory status precedence classifies tracks with internal gaps as `active` if they touch the final video frame.
- Interior track termination cannot be treated as definitive physical tracker fragmentation without manual ground truth.

---

## 2. Repository State Verification

- **Active Branch**: `antigravity/v1.0.2`
- **HEAD Commit**: `364ce80`
- **Parent Commit**: `7556381`
- **Working Tree**: Clean (all changes tracked and committed).
- **Inspected Files**:
  - `backend/trajectories.py` (364 lines)
  - `backend/visualization.py` (222 lines)
  - `backend/services/visualization.py` (263 lines)
  - `backend/database/repository.py` (162 lines)
  - `backend/config.py` (187 lines)
  - `configs/default.yaml` (62 lines)
  - `backend/cli.py` (124 lines)
  - `docs/handoffs/phase_04/HANDOFF.md` (135 lines)
  - `PHASE_04_VALIDATION_REPORT.md` (133 lines)
  - `tests/test_trajectories.py` (14 tests)
  - `tests/test_visualization.py` (11 tests)
  - `tests/test_phase_04_audit.py` (4 audit probes)

---

## 3. Findings Matrix

| ID | Severity | Category | Description | Impact |
|---|---|---|---|---|
| **F-04-01** | **High** | Visualization | **Motion trails bridge unobserved temporal gaps**: When a track has missing frames or long temporal gaps, `cv2.polylines` draws a straight line connecting points before and after the gap. | Fabricates visual continuity across periods of occlusion or detector loss. |
| **F-04-02** | **Medium** | Methodology | **`active` status takes precedence over internal gap fragmentation**: A track that spans large gaps (e.g. 10s) but touches `last_video_frame` is marked `active` rather than `fragmented`. | Conceals severe tracking discontinuity if the vehicle is observed on the final frame. |
| **F-04-03** | **Medium** | Methodology | **Conflating interior disappearance with physical fragmentation**: A track ending inside the scene without reaching the 20px frame boundary is classified as `fragmented`. | Stationary vehicles, stopped queues, or mid-scene occlusions are mislabeled as tracker failures. |
| **F-04-04** | **Low** | Architecture | **`build_trajectories` groups by `track_id` alone instead of `(run_id, track_id)`**: Passing multi-run observations pools identical track IDs and flags them as `invalid`. | Safe within `build_run_trajectories` (which filters by run), but fragile for multi-run datasets. |
| **F-04-05** | **Low** | CLI / Service | **Unvalidated frame ranges in CLI and service**: `--start-frame` and `--end-frame` do not validate $start \le end$ or non-negativity, producing silent 0-frame MP4 files if inverted. | Minor usability issue; creates empty video artifacts without clear error messages. |

---

## 4. Detailed Audit Findings & Evidence

### F-04-01: Motion Trails Bridge Unobserved Temporal Gaps (High)
- **Location**: `backend/visualization.py`, lines 115–135
- **Evidence**:
  ```python
  if cfg.show_trails and cfg.trail_length > 0:
      past_points = [
          (p.ground_x, p.ground_y)
          for p in trajectory.points
          if p.frame_number <= frame_number
      ]
      if len(past_points) >= 2:
          recent_points = past_points[-cfg.trail_length :]
          pts_arr = np.array(
              [[int(gx), int(gy)] for gx, gy in recent_points],
              dtype=np.int32,
          ).reshape((-1, 1, 2))
          cv2.polylines(canvas, [pts_arr], isClosed=False, ...)
  ```
- **Audit Verification**: Demonstrated by audit test `test_audit_motion_trail_connects_across_unobserved_gaps` in `tests/test_phase_04_audit.py`. When a vehicle is observed at frame 1 and frame 100 with a 99-frame gap, `cv2.polylines` renders a direct geometric line between (20, 20) and (100, 100), drawing pixels through unobserved scene areas.
- **Recommendation**: Split `recent_points` into disjoint polyline segments whenever consecutive observations exceed `max_gap_seconds` (or frame stride gap).

---

### F-04-02: `active` Status Takes Precedence Over Internal Gaps (Medium)
- **Location**: `backend/trajectories.py`, lines 301–321
- **Evidence**:
  ```python
  elif last_video_frame is not None and points[-1].frame_number >= last_video_frame:
      status = STATUS_ACTIVE
      status_reason = f"Track remains active on final video frame ({points[-1].frame_number})"
  else:
      ...
      if internal_gaps:
          status = STATUS_FRAGMENTED
  ```
- **Audit Verification**: Demonstrated by audit test `test_audit_active_status_precedence_over_internal_gaps`. A vehicle observed at frame 1 and frame 100 (9.9s gap) on a 100-frame clip receives `status = 'active'`, completely suppressing the `fragmented` classification.
- **Recommendation**: If `internal_gaps` is non-empty, classify as `fragmented` (or record composite status / flag `is_incomplete = True`) regardless of whether the final observation touches `last_video_frame`.

---

### F-04-03: Conflating Interior Disappearance with Physical Fragmentation (Medium)
- **Location**: `backend/trajectories.py`, lines 322–326
- **Evidence**:
  ```python
  elif exited_boundary is False:
      status = STATUS_FRAGMENTED
      status_reason = "Track terminated in scene interior without reaching frame boundary"
  ```
- **Analysis**: In urban intersections like Pattom:
  - Vehicles frequently stop in queues, park along kerbsides, or turn into driveways.
  - Tracker loss can occur due to static occlusion (billboards, bus shelters, overpasses).
  - Calling this `fragmented` asserts that one physical vehicle received multiple track IDs, which is an unsupported inference.
- **Recommendation**: Retain `suspected_fragmentation` in diagnostics with the existing uncertainty disclaimer, but document in Phase 05/06 that interior termination is an indicator of track termination, not confirmed identity fragmentation.

---

### F-04-04: Cross-Run Track ID Pooling in `build_trajectories` (Low)
- **Location**: `backend/trajectories.py`, lines 174–177
- **Evidence**:
  ```python
  grouped_rows: dict[int, list[Any]] = defaultdict(list)
  for row in observations:
      track_id = int(row["track_id"])
      grouped_rows[track_id].append(row)
  ```
- **Audit Verification**: Demonstrated by `test_audit_cross_run_track_id_collision`. If rows from multiple runs share `track_id=1`, they are grouped together and then marked `invalid` due to conflicting `run_id`.
- **Mitigation**: `build_run_trajectories()` in the service layer queries `tracks` with `WHERE run_id = ?`, so this does not occur in standard execution. However, `build_trajectories` should group by `(run_id, track_id)` for general utility.

---

### F-04-05: Unvalidated Frame Range Parameters (Low)
- **Location**: `backend/services/visualization.py`, lines 201–206, `backend/cli.py`
- **Evidence**:
  If `--start-frame 50 --end-frame 10` is passed, the loop skips frames $< 50$ and breaks when $> 10$, writing an empty 0-frame video without raising a validation error.
- **Recommendation**: Add a pre-check `if start_frame is not None and end_frame is not None and start_frame > end_frame: raise ValueError(...)`.

---

## 5. Civil Engineering Research Validity

| Dimension | Current Implementation State | Research Validity & Limitations |
|---|---|---|
| **Road Surface Projection** | Bounding-box bottom-centre `((x1+x2)/2, y2)` | **Valid Approximation**: Correctly avoids elevating the road point to the 3D vehicle centre. However, on inclined approaches, slight planar distortion persists until Phase 07 homography. |
| **Pixel vs Metric Coordinates** | Pixel space only (`ground_x, ground_y`); `world_x, world_y = NULL` | **Strictly Compliant**: Metric distance measurements remain blocked. No metric coordinates are fabricated. |
| **Track Count vs Traffic Volume** | Raw `track_id` counts | **NOT Safe for Traffic Volumes**: Raw track counts are inflated by fragmentation and false detections. Screenline counts require Phase 05/06. |
| **Motion Continuity** | Kalman filter + IoU association | **Heuristic Only**: Apparent track continuity does not guarantee zero ID switches in dense mixed traffic. Real accuracy requires manual MOT ground truth. |
| **Speed & Queue Length** | Blocked | **Strictly Blocked**: Calibrated speed and metric queue estimation remain disabled until Phases 07, 08, and 09. |

---

## 6. Test Suite Execution & Audit Evidence

### Regression & Audit Test Execution
Commands executed independently during audit:
```bash
uv run pytest -v
```

**Results:**
```text
============================= test session starts =============================
platform win32 -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0
rootdir: D:\Work\Personal\traffic-vision-final-year-project
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.15.1
collected 58 items

tests/test_app.py::test_health_endpoint_reports_phase_one PASSED         [  1%]
tests/test_app.py::test_status_endpoint_is_phase_one_only PASSED         [  3%]
tests/test_config.py::test_config_hash_is_stable_for_equivalent_mappings PASSED [  5%]
tests/test_config.py::test_config_rejects_non_decoder_pts_strategy PASSED [  6%]
tests/test_database.py::test_bootstrap_enables_foreign_keys_on_every_connection PASSED [  8%]
tests/test_database.py::test_bootstrap_is_idempotent PASSED              [ 10%]
tests/test_database.py::test_bootstrap_rejects_a_database_with_an_unknown_schema PASSED [ 12%]
tests/test_detection.py::test_mapping_requires_explicit_project_class PASSED [ 13%]
tests/test_detection.py::test_tile_generation_covers_frame_edges_deterministically PASSED [ 15%]
tests/test_detection.py::test_tile_merge_is_class_aware_and_deterministic PASSED [ 17%]
tests/test_detection.py::test_roi_crop_validates_and_preserves_offsets PASSED [ 18%]
tests/test_detection_service.py::test_detection_run_persists_only_canonical_detections PASSED [ 20%]
tests/test_ingestion.py::test_ingestion_persists_metadata_run_and_decoder_pts PASSED [ 22%]
tests/test_ingestion.py::test_preview_decodes_one_requested_frame_sequentially PASSED [ 24%]
tests/test_media.py::test_timestamp_audit_marks_variable_cadence PASSED  [ 25%]
tests/test_media.py::test_timestamp_audit_marks_missing_or_non_monotonic_pts PASSED [ 27%]
tests/test_phase_04_audit.py::test_audit_cross_run_track_id_collision PASSED [ 29%]
tests/test_phase_04_audit.py::test_audit_active_status_precedence_over_internal_gaps PASSED [ 31%]
tests/test_phase_04_audit.py::test_audit_motion_trail_connects_across_unobserved_gaps PASSED [ 32%]
tests/test_phase_04_audit.py::test_audit_zero_area_bounding_box PASSED   [ 34%]
tests/test_tracking.py::test_cadence_to_frames_conversion PASSED         [ 36%]
tests/test_tracking.py::test_detection_batch_properties_and_slicing PASSED [ 37%]
tests/test_tracking.py::test_persistent_id_association_across_frames PASSED [ 39%]
tests/test_tracking.py::test_empty_frame_handling PASSED                 [ 41%]
tests/test_tracking.py::test_missed_detection_reconnection_within_buffer PASSED [ 43%]
tests/test_tracking.py::test_evaluate_id_switches_known_switch_and_no_switch PASSED [ 44%]
tests/test_tracking.py::test_resolve_track_class_majority_voting_and_preservation PASSED [ 46%]
tests/test_tracking.py::test_resolve_track_class_deterministic_tie_breaking PASSED [ 48%]
tests/test_tracking.py::test_resolve_track_class_empty_and_low_confidence PASSED [ 50%]
tests/test_tracking_service.py::test_tracking_run_persists_canonical_tracks PASSED [ 51%]
tests/test_tracking_service.py::test_tracking_bounded_memory_batch_persistence PASSED [ 53%]
tests/test_tracking_service.py::test_tracking_atomic_rollback_on_database_failure PASSED [ 55%]
tests/test_tracking_service.py::test_tracking_rejects_missing_or_incomplete_parent_run PASSED [ 56%]
tests/test_trajectories.py::test_compute_ground_point_bottom_center_calculation PASSED [ 58%]
tests/test_trajectories.py::test_compute_ground_point_rejects_bbox_center_and_unsupported_methods PASSED [ 60%]
tests/test_trajectories.py::test_compute_ground_point_rejects_malformed_coordinates PASSED [ 62%]
tests/test_trajectories.py::test_build_trajectories_deterministic_chronological_ordering PASSED [ 63%]
tests/test_trajectories.py::test_build_trajectories_preserves_raw_observations_without_interpolation PASSED [ 65%]
tests/test_trajectories.py::test_build_trajectories_class_consensus_integration PASSED [ 67%]
tests/test_trajectories.py::test_build_trajectories_status_active PASSED [ 68%]
tests/test_trajectories.py::test_build_trajectories_status_complete_exiting_boundary PASSED [ 70%]
tests/test_trajectories.py::test_build_trajectories_status_fragmented_on_prolonged_gap PASSED [ 72%]
tests/test_trajectories.py::test_build_trajectories_status_fragmented_on_interior_termination PASSED [ 74%]
tests/test_trajectories.py::test_build_trajectories_status_invalid_on_malformed_box PASSED [ 75%]
tests/test_trajectories.py::test_build_trajectories_status_invalid_on_duplicate_frame PASSED [ 77%]
tests/test_trajectories.py::test_build_trajectories_status_invalid_on_non_monotonic_timestamp PASSED [ 79%]
tests/test_trajectories.py::test_build_trajectories_empty_and_trail_helpers PASSED [ 81%]
tests/test_visualization.py::test_visualization_config_defaults_and_overrides PASSED [ 82%]
tests/test_visualization.py::test_get_track_color_deterministic PASSED   [ 84%]
tests/test_visualization.py::test_render_frame_annotations_deterministic_output PASSED [ 86%]
tests/test_visualization.py::test_render_frame_annotations_toggles PASSED [ 87%]
tests/test_visualization.py::test_render_frame_annotations_empty_tracks_returns_clean_copy PASSED [ 89%]
tests/test_visualization.py::test_render_frame_annotations_handles_out_of_bounds_and_invalid_boxes PASSED [ 91%]
tests/test_visualization.py::test_build_run_trajectories_service PASSED  [ 93%]
tests/test_visualization.py::test_render_preview_visualization_creates_image PASSED [ 94%]
tests/test_visualization.py::test_render_video_visualization_lineage_and_provenance PASSED [ 96%]
tests/test_visualization.py::test_render_video_visualization_rejects_missing_or_incomplete_parent PASSED [ 98%]
tests/test_visualization.py::test_render_video_visualization_interruption_cleanup PASSED [100%]

============================= 58 passed in 5.34s ==============================
```

---

## 7. Phase 05 Readiness Decision

**Decision: READY TO PROCEED TO PHASE 05 (Subject to Condition Acceptance).**

### Acceptance Conditions:
1. **Downstream Consumption Contract**: Phase 05 (ROI, entry/exit zones, counting lines) must consume `TrajectoryPoint.ground_x` and `ground_y` (bottom-centre) for line-crossing ray intersections, NOT bounding-box centres.
2. **Status Reliance**: Phase 06 counting must not rely solely on `trajectory_status == 'complete'` to include tracks; tracks with valid entry and exit zone crossings should be counted regardless of minor interior gaps.
3. **Trail Gap Segmentation**: During future UI refinement, motion trail rendering should be updated to break polylines across unobserved frame gaps exceeding `max_gap_seconds`.
