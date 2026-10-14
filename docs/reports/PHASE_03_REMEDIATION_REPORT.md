# Phase 03 Remediation Report — ByteTrack Integration & Phase 04 Readiness

**Remediation Date:** October 11, 2026  
**Engineer:** Senior Computer-Vision Engineer & Database Reliability Engineer  
**Target Branch:** `antigravity/v1.0.2`  
**Starting Audit:** `PHASE_03_VALIDATION_REPORT.md`  
**Base Commit:** `f0353bd875885ec8c8dc3bb0b48dcc3cd8396295` (`codex/v1.0.1`)  

---

## 1. Executive Summary & Readiness Verdict

### **Verdict: READY FOR PHASE 04 (APPROVED)**

All three confirmed defects identified during the independent audit have been resolved:
1. **Misleading ID-Switch Reporting:** Removed the unmeasured `0` metric; `TrackingMetrics.id_switches` is now explicitly `None` (`unmeasured`) on unlabelled video runs, and a dedicated, mathematically sound evaluation function `evaluate_id_switches()` was implemented and verified with crossing-target test fixtures.
2. **Class Jitter Instability:** Implemented `resolve_track_class()`, an immutable confidence-weighted voting helper with deterministic alphabetical tie-breaking, guaranteeing consistent track-level vehicle classification while preserving raw per-frame observation labels.
3. **Unbounded Memory Persistence:** Replaced whole-video list accumulation with configurable streaming batches (`batch_size`, default 500) participating in a single atomic database transaction. Verified atomic rollback on mid-stream failure with zero orphaned rows.

The full test suite expands from 23 to **29 passing tests**, and the repository satisfies all preconditions for Phase 04 (`Trajectories and Visualization`).

---

## 2. Changes Made & Exact Files Modified

```
+--------------------------------------+-----------------------------------------------------------------------------------------------+
| File Path                            | Nature of Change                                                                              |
+--------------------------------------+-----------------------------------------------------------------------------------------------+
| backend/tracking.py                  | - Changed TrackingMetrics.id_switches to int | None = None (explicitly unmeasured without GT).   |
|                                      | - ByteTrackerAdapter.metrics reports id_switches = None for unlabelled video.                 |
|                                      | - Added evaluate_id_switches(ground_truth_assignments) for CLEAR MOT evaluation.               |
|                                      | - Added resolve_track_class(observations) with confidence-weighted voting & tie-breaking.     |
+--------------------------------------+-----------------------------------------------------------------------------------------------+
| backend/services/tracking.py         | - Implemented bounded-memory persistence using streaming batch flushes (batch_size).          |
|                                      | - Wrapped batch inserts in atomic SQLite transaction with full rollback on exception.         |
|                                      | - Updated run notes logging to explicitly state id_switches=unmeasured when unmeasured.       |
+--------------------------------------+-----------------------------------------------------------------------------------------------+
| tests/test_tracking.py               | - Added test_evaluate_id_switches_known_switch_and_no_switch.                                  |
|                                      | - Added test_resolve_track_class_majority_voting_and_preservation.                            |
|                                      | - Added test_resolve_track_class_deterministic_tie_breaking.                                  |
|                                      | - Added test_resolve_track_class_empty_and_low_confidence.                                     |
|                                      | - Updated test_persistent_id_association_across_frames to assert id_switches is None.         |
+--------------------------------------+-----------------------------------------------------------------------------------------------+
| tests/test_tracking_service.py       | - Added test_tracking_bounded_memory_batch_persistence (verifies multi-batch flushing).        |
|                                      | - Added test_tracking_atomic_rollback_on_database_failure (verifies rollback on mid-run error).|
|                                      | - Updated run notes assertion to verify id_switches=unmeasured.                               |
+--------------------------------------+-----------------------------------------------------------------------------------------------+
| docs/handoffs/phase_03/HANDOFF.md    | - Updated delivered interfaces, test counts (29 passed), memory guarantees, and contracts.    |
+--------------------------------------+-----------------------------------------------------------------------------------------------+
```

---

## 3. Before-and-After Behaviour Analysis

### Finding 1: Unmeasured ID Switches
* **Before:** `TrackingMetrics.id_switches` was hardcoded to `0`. Every tracking run recorded `id_switches=0` in its database notes, misleading researchers into believing identity was perfectly preserved with zero switches.
* **After:**
  * When executing on unlabelled video (standard inference), `tracker.metrics.id_switches` returns `None`, and the processing run notes explicitly record `id_switches=unmeasured`.
  * For benchmarking datasets with ground-truth identity annotations, `evaluate_id_switches(ground_truth_assignments)` evaluates true CLEAR MOT identity switches.
  * Verified: Two vehicles swapping tracks increment `id_switches` by 2; missed detections without a switch do not trigger a false count.

### Finding 2: Single-Track Class Instability Under Detector Jitter
* **Before:** `tracks.vehicle_class` directly recorded the per-frame detection class. If YOLO jittered between `car` and `truck` on alternating frames, the single vehicle track recorded conflicting classes, compromising downstream vehicle counting (Phase 06).
* **After:**
  * `resolve_track_class(observations)` performs confidence-weighted voting with deterministic tie-breaking.
  * 5 `car` observations (conf 0.9 each, score 4.5) + 1 `truck` observation (conf 0.9, score 0.9) resolve deterministically to `car`.
  * The raw historical per-frame classes in `TrackObservation` remain completely unmutated.
  * Downstream civil-engineering components (Phase 04 visualization, Phase 06 counting) can display and aggregate by the resolved class while preserving raw detection provenance.

### Finding 3: In-Memory Observation Accumulation
* **Before:** `run_tracking()` accumulated all `TrackObservation` objects across the entire video in a Python list `all_observations`, then duplicated them into a second list `track_rows` before calling `insert_tracks()`. For 1-hour 1080p footage with high traffic, this created unbounded memory consumption.
* **After:**
  * Observations are held in memory only up to `batch_size` (default 500, configurable via `configs/default.yaml`).
  * As soon as `len(pending_rows) >= batch_size`, the batch is flushed to SQLite via `insert_tracks(connection, pending_rows)`.
  * Any remaining partial batch is flushed cleanly at video end.
  * Python RAM allocation for pending observations remains $O(B)$ bounded.

---

## 4. Database Transaction & Failure-Recovery Architecture

```
+-----------------------------------------------------------------------------------------------------------------------+
| BOUNDED-MEMORY STREAMING WITH ATOMIC TRANSACTION ROLLBACK                                                            |
+-----------------------------------------------------------------------------------------------------------------------+
|                                                                                                                       |
|  Frame Loop (Streaming)                                                                                               |
|  ├─► Frame 001..025: Observations accumulated in RAM (count = 500)                                                    |
|  │   └─► insert_tracks(connection, batch_1) ──► written to SQLite uncommitted journal                                |
|  ├─► Frame 026..050: Observations accumulated in RAM (count = 500)                                                    |
|  │   └─► insert_tracks(connection, batch_2) ──► written to SQLite uncommitted journal                                |
|  │                                                                                                                    |
|  ├── [NORMAL COMPLETION PATH]                                                                                         |
|  │   ├─► Flush partial final batch (count < 500)                                                                      |
|  │   ├─► connection.commit()                                                                                          |
|  │   └─► update_run_status(connection, run_id, status='completed', notes='... id_switches=unmeasured')              |
|  │                                                                                                                    |
|  └── [FAILURE PATH (e.g. simulated I/O error on Batch 2)]                                                             |
|      ├─► Exception raised inside database_connection context                                                          |
|      ├─► connection.rollback() executes automatically                                                                 |
|      ├─► Batch 1 and Batch 2 are completely wiped from `tracks` table (0 orphaned rows)                              |
|      └─► Separate connection records: update_run_status(connection, run_id, status='failed', notes=error)            |
+-----------------------------------------------------------------------------------------------------------------------+
```

### Verified Failure-Recovery Guarantees:
1. **No Partial Output Mistaken for Success:** If an error occurs on batch 2 of a 5-batch run, SQLite rolls back batch 1 immediately. The `tracks` table contains 0 rows for that `run_id`.
2. **Accurate Terminal State:** The processing run is marked with `status = 'failed'` and records the exact exception message in `notes`.
3. **Idempotence & Re-runs:** Re-running tracking on the parent detection creates a new `run_id` with a clean state.

---

## 5. Automated Test Execution & Evidence

```text
Command: uv run pytest -v
Result: 29 passed in 4.12s
Environment: Windows AMD64, Python 3.12.13, pytest-9.1.1
```

### Detailed Breakdown of Test Suite:
* **Phase 01 Tests (7 passed):**
  * `test_health_endpoint_reports_phase_one`
  * `test_status_endpoint_is_phase_one_only`
  * `test_bootstrap_enables_foreign_keys_on_every_connection`
  * `test_bootstrap_is_idempotent`
  * `test_bootstrap_rejects_a_database_with_an_unknown_schema`
  * `test_ingestion_persists_metadata_run_and_decoder_pts`
  * `test_preview_decodes_one_requested_frame_sequentially`
* **Phase 02 Tests (9 passed):**
  * `test_config_hash_is_stable_for_equivalent_mappings`
  * `test_config_rejects_non_decoder_pts_strategy`
  * `test_mapping_requires_explicit_project_class`
  * `test_tile_generation_covers_frame_edges_deterministically`
  * `test_tile_merge_is_class_aware_and_deterministic`
  * `test_roi_crop_validates_and_preserves_offsets`
  * `test_detection_run_persists_only_canonical_detections`
  * `test_timestamp_audit_marks_variable_cadence`
  * `test_timestamp_audit_marks_missing_or_non_monotonic_pts`
* **Phase 03 Tests (13 passed):**
  * `test_cadence_to_frames_conversion`
  * `test_detection_batch_properties_and_slicing`
  * `test_persistent_id_association_across_frames`
  * `test_empty_frame_handling`
  * `test_missed_detection_reconnection_within_buffer`
  * `test_evaluate_id_switches_known_switch_and_no_switch` **[NEW]**
  * `test_resolve_track_class_majority_voting_and_preservation` **[NEW]**
  * `test_resolve_track_class_deterministic_tie_breaking` **[NEW]**
  * `test_resolve_track_class_empty_and_low_confidence` **[NEW]**
  * `test_tracking_run_persists_canonical_tracks`
  * `test_tracking_bounded_memory_batch_persistence` **[NEW]**
  * `test_tracking_atomic_rollback_on_database_failure` **[NEW]**
  * `test_tracking_rejects_missing_or_incomplete_parent_run`

---

## 6. Remaining Risks & Documented Limitations

1. **Two-Frame Confirmation Latency:**  
   ByteTrack requires two consecutive detections to confirm a track (except on frame 1). Vehicles entering on frame $K > 1$ appear in `tracks` starting at frame $K+1$. Phase 04 and Phase 05 entry-zone geometry must accommodate this 1-frame latency.
2. **Trajectory Gaps During Temporary Occlusions:**  
   ByteTrack does not fabricate synthetic bounding boxes during temporary missed frames within the buffer window. Trajectories will have frame gaps during occlusions. Phase 04 must render disjoint trails honestly without inventing linear interpolation.
3. **Pending Real-Footage Validation:**  
   No Pattom Junction CCTV video clips are currently staged on disk. All tracking validation has been proven through mathematical proofs and synthetic software fixtures. Real mixed-traffic evaluation remains pending user footage staging.

---

## 7. Phase 04 Readiness Contract

Phase 04 (`Trajectories and Visualization`) is **authorized to proceed**. Its implementation must conform to the following contract:

1. **Input Queries:** Consume `tracks` ordered deterministically by `run_id`, `track_id`, `frame_number ASC`.
2. **Ground-Point Rule:** Use bottom-centre `(ground_x, ground_y)` as the default road-contact point; keep bounding box coordinates `(x1, y1, x2, y2)` separate.
3. **Class Rendering:** Display the track-level consensus class using `resolve_track_class(track_observations)` while preserving per-frame observation data.
4. **Trajectory Continuity:** Handle missing frames without fabricating artificial positions. Label fragmented or terminated tracks honestly.
5. **Coordinate Boundary:** Treat coordinates strictly as image pixels. Do not perform world-coordinate or speed conversions until Phase 07 calibration is accepted.
