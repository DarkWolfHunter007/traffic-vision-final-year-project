# Phase 03 Independent Validation Report — ByteTrack Integration

**Audit Date:** October 11, 2026  
**Auditor:** Senior Python Engineer, Computer-Vision Researcher, Database Integrity Auditor & QA Engineer  
**Target Branch:** `antigravity/v1.0.2`  
**Base Commit (Inherited):** `codex/v1.0.1` @ commit `f0353bd875885ec8c8dc3bb0b48dcc3cd8396295`  
**Working-Tree State:** Uncommitted Phase 03 implementation files  
**Target Study Site:** Pattom Intersection, Thiruvananthapuram, Kerala, India  

---

## 1. Executive Verdict

### **Verdict: CONDITIONAL PASS**

The Phase 03 ByteTrack integration is **technically sound, database-safe, reproducible, and correctly decoupled from `model.track()`**. It establishes an immutable child processing run, respects the canonical SQLite schema constraints, enforces per-connection foreign keys, and persists bottom-centre ground points without falsifying world coordinates or calibration references.

However, the pass is **CONDITIONAL** upon acknowledging and managing three technical and civil-engineering constraints before Phase 04 and Phase 06:
1. **Uncalculated ID-Switch Metric:** Tracking quality metric `self._id_switches` is currently hardcoded to `0` and never computed during runtime.
2. **Class-Agnostic Trajectory Jitter:** ByteTrack associates bounding boxes purely via spatial IoU distance; individual observations within the same `track_id` can record conflicting vehicle classes under YOLO label jitter. Downstream phases must apply trajectory-level class voting.
3. **Pending Real-World Validation:** Zero physical Pattom CCTV clips are staged locally. All 23 passing tests rely on synthetic software media fixtures.

---

## 2. Exact Repository & Working-Tree State Audited

* **Branch:** `antigravity/v1.0.2` (created directly from `codex/v1.0.1`)
* **HEAD Commit:** `f0353bd875885ec8c8dc3bb0b48dcc3cd8396295` (`feat: add phase two detection pipeline`)
* **Parent Commits:**
  * `ce40f89`: `feat: add phase one ingestion foundation`
  * `504adc8`: `docs: consolidate methodology and design handover`
  * `900c7d1`: `docs: add independent technical audit prompt`
* **Uncommitted Phase 03 Implementation Files:**
  * `modified: pyproject.toml` (added `lap>=0.5.12`)
  * `modified: uv.lock` (locked `lap==0.5.13`)
  * `modified: configs/default.yaml` (added `tracking` configuration block)
  * `modified: backend/config.py` (added tracking defaults and configuration validation)
  * `modified: backend/database/repository.py` (added `insert_tracks` and `fetch_detections_for_tracking`)
  * `modified: backend/cli.py` (added `traffic-vision track` CLI command)
  * `untracked: backend/tracking.py` (cadence conversion, DetectionBatch adapter, ByteTrackerAdapter)
  * `untracked: backend/services/tracking.py` (run_tracking service orchestrator)
  * `untracked: tests/test_tracking.py` (unit test suite for tracking primitives)
  * `untracked: tests/test_tracking_service.py` (integration test suite with synthetic fixtures)
  * `untracked: docs/handoffs/phase_03/HANDOFF.md` (Phase 03 delivery documentation)

---

## 3. Files & Interfaces Inspected

1. `pyproject.toml` & `uv.lock`: Dependency constraints and wheel availability for `lap`.
2. `backend/tracking.py`: `cadence_to_frames`, `DetectionBatch`, `TrackObservation`, `TrackingMetrics`, and `ByteTrackerAdapter`.
3. `ultralytics.trackers.byte_tracker`: Installed dependency source inspected in `.venv`:
   * `BYTETracker.__init__` and `BYTETracker.update`
   * `STrack.activate`, `STrack.update`, `STrack.result`
   * `BYTETracker._split_detections`, `BYTETracker._init_new_tracks`, `BYTETracker._format_output`
4. `backend/database/schema.sql`: Table definition for `tracks`, indexes, and check constraints.
5. `backend/database/connection.py`: Foreign key PRAGMA enforcement and transactional rollback behaviour.
6. `backend/database/repository.py`: `insert_tracks` and `fetch_detections_for_tracking`.
7. `backend/services/tracking.py`: `run_tracking` lifecycle and frame iteration loop.
8. `backend/cli.py`: CLI parser registration and error handling.
9. `tests/test_tracking.py` & `tests/test_tracking_service.py`: Test coverage and synthetic fixtures.
10. `docs/handoffs/phase_03/HANDOFF.md` & `walkthrough.md`: Handoff documentation and claims.

---

## 4. Test Execution & Independent Experiments

### A. Repository Test Suite Execution
```text
Command: uv run pytest -v
Result: 23 passed in 3.53s
Platform: Windows (AMD64), Python 3.12.13, pytest-9.1.1
```
* Phase 01: 7 tests passed (ingestion, PTS audit, minimal API, database bootstrap)
* Phase 02: 9 tests passed (config validation, tile generation, NMS merging, detection service)
* Phase 03: 7 tests passed (cadence conversion, batch slicing, ID retention across frames, empty frames, reconnection within buffer, tracking service persistence, invalid parent run rejection)

### B. Targeted Independent Adversarial Experiments (Scratch Tests)
1. **Zero-Detection Video Run:** Ingested and ran tracking on a video with 0 detections. Run transitioned cleanly to `status = 'completed'` with 0 track rows and logged `total_tracks=0, observations=0`.
2. **Crossing Targets:** Simulated two vehicles moving toward each other and crossing paths at identical Y coordinates. Kalman filter velocity momentum preserved separate track IDs (Track 1 and Track 2) across all 11 frames.
3. **Parallel Trajectories:** Simulated two closely spaced motorcycles moving forward with only 5 pixels lateral separation. ByteTrack maintained distinct track IDs and correct spatial lanes.
4. **Temporary Occlusion by Bus:** Simulated a motorcycle occluded for 2 frames behind a bus. When the motorcycle reappeared, ByteTrack re-associated it with the original track ID within the buffer window.
5. **Class Jitter Experiment:** Passed Detection 1 as `car` on frame 1, and Detection 1 as `truck` on frame 2. ByteTrack matched the track based on spatial IoU, resulting in observation 1 recording `car` and observation 2 recording `truck` under the same `track_id`.

---

## 5. Findings & Defect Classification

```
+----+----------+--------------------------------------------------------+-------------------------------------------------------------+
| ID | Severity | Finding Summary                                        | Impact / Root Cause                                         |
+----+----------+--------------------------------------------------------+-------------------------------------------------------------+
| 01 | HIGH     | ID-Switch Instrumentation Hardcoded to Zero            | Metric self._id_switches in backend/tracking.py is initialized|
|    |          |                                                        | to 0 and never calculated during frame updates.             |
+----+----------+--------------------------------------------------------+-------------------------------------------------------------+
| 02 | HIGH     | Single Track Class Instability Under Detector Jitter   | ByteTrack is class-agnostic; observations in tracks table   |
|    |          |                                                        | inherit per-frame detector labels without track-level voting.|
+----+----------+--------------------------------------------------------+-------------------------------------------------------------+
| 03 | MEDIUM   | All Observations Accumulated in Memory Before Insert   | run_tracking holds entire video's track rows in a list,     |
|    |          |                                                        | which scales with O(N_frames * N_vehicles).                 |
+----+----------+--------------------------------------------------------+-------------------------------------------------------------+
| 04 | MEDIUM   | First Entry Frame Omitted by Two-Frame Confirmation   | STrack.activate only sets is_activated=True on frame 1;     |
|    |          |                                                        | tracks entering on frame K>1 appear in tracks at frame K+1. |
+----+----------+--------------------------------------------------------+-------------------------------------------------------------+
| 05 | LOW      | Kalman Filter Assumes Constant Discrete Time Step      | ByteTrack frame updates assume dt=1; variable frame rates   |
|    |          |                                                        | or dropped frames do not scale Kalman velocity transitions. |
+----+----------+--------------------------------------------------------+-------------------------------------------------------------+
| 06 | INFO     | Real Pattom CCTV Footage Pending Ingestion             | 0 real Pattom clips available locally; validation on real    |
|    |          |                                                        | mixed traffic occlusions remains pending field data.        |
+----+----------+--------------------------------------------------------+-------------------------------------------------------------+
```

---

## 6. Detailed Technical Audit

### 6.1 ByteTrack Adapter & Dependency Constraints
* **Installed Implementation:** The adapter wraps `ultralytics.trackers.byte_tracker.BYTETracker` from `ultralytics==8.3.250`.
* **Constructor API:** `BYTETracker(args)` expects a namespace containing `track_high_thresh`, `track_low_thresh`, `new_track_thresh`, `track_buffer`, `match_thresh`, and `fuse_score`. `ByteTrackerAdapter` constructs this namespace explicitly.
* **Dependency Locking:** `lap>=0.5.12` is declared in `pyproject.toml` and pinned to `lap==0.5.13` in `uv.lock` with pre-compiled wheels for Windows, Linux, and macOS. Linear assignment runs without runtime compilation or interactive downloads.
* **Separation of Concerns:** `ByteTrackerAdapter` operates purely on pre-computed detections. It **never calls `model.track()`** and does not load detector weights, strictly honoring the Phase 03 boundary.

### 6.2 Cadence & Time Semantics
* **Conversion Formula:**
  $$\text{effective\_fps} = \frac{\text{nominal\_fps}}{\max(1, \text{frame\_stride})}$$
  $$\text{track\_buffer\_frames} = \max\left(1, \operatorname{round}(\text{buffer\_seconds} \times \text{effective\_fps})\right)$$
* **Validation:** Verified across nominal FPS (15, 25, 29.97, 30) and frame strides (1, 2, 5). Zero and negative inputs correctly raise `TrackingError`.
* **Time Distinction:**
  1. *Tracker Motion Model:* Discrete frame step index ($k \in \mathbb{N}$).
  2. *Buffer Window:* Discrete frame window derived from nominal FPS.
  3. *Stored Observation Time:* Authoritative decoder PTS (`timestamp_s`) inherited from `video_frames`.

### 6.3 Ground-Point Calculation
* **Formula:** `ground_x = (x1 + x2) / 2.0`, `ground_y = y2`
* **Coordinate Space:** Stored explicitly as image pixel coordinates.
* **Database Isolation:** `world_x` and `world_y` are set to `NULL`, and `calibration_id` is set to `NULL`.
* **Constraint Compliance:** Satisfies `backend/database/schema.sql` line 89:
  `CHECK ((world_x IS NULL AND world_y IS NULL) OR calibration_id IS NOT NULL)`
* **Physical Limitations for Traffic Analysis:**
  * Bottom-centre represents the tyre contact patch on planar road surfaces.
  * Truncated vehicles exiting the frame bottom will have their ground point pinned to the bottom image boundary ($y_2 = H$), creating artificial velocity spikes.
  * Cast shadows at morning/evening low sun angles artificially depress $y_2$, displacing the ground point into adjacent lanes.

### 6.4 Database Integrity & Provenance
* **Parent-Child Lineage:** `run_tracking` verifies `parent_run_id` exists, belongs to the same video, and is in terminal `status = 'completed'`. Attempting to track an invalid, incomplete, or failed run raises `ValueError`.
* **Transactions:** Managed via `database_connection()` context manager. Any mid-stream failure executes `connection.rollback()` and records `status = 'failed'` in a separate transaction.
* **No Uncontrolled Collisions:** Re-running tracking on the same parent detection run creates a distinct child run with a unique UUID `run_id` and unique `track_observation_id` primary keys.

---

## 7. Real-World Tracking Validity Assessment (Pattom Site Context)

### Current Footage Status: PENDING INGESTION
An exhaustive local audit confirmed **0 Pattom Junction CCTV video clips** are present on disk. The repository contains only synthetic software fixtures generated by FFmpeg.

### Real-Footage Validation Protocol (For Delivered Pattom Footage)
When representative Pattom footage is staged, the following validation procedure must be executed:
1. **Test Clip Selection:** Select three 15-minute intervals:
   * *Peak AM (09:00 - 09:15 IST):* Dense queueing, high two-wheeler density.
   * *Off-Peak Midday (13:00 - 13:15 IST):* Free flow, turning movements.
   * *Dusk (18:15 - 18:30 IST):* Streetlights and headlight glare.
2. **Manual Ground-Truth Protocol:**
   * Sample 50 distinct vehicles across 5 vehicle classes (2W, Auto-rickshaw, Car, Bus, LCV).
   * Record true entry frame, true exit frame, and track continuity.
3. **Tracking Metrics to Evaluate:**
   * **MOTA (Multiple Object Tracking Accuracy):** False positives, misses, and ID switches.
   * **Track Fragmentation:** Count of disconnected track IDs assigned to single physical vehicles.
   * **ID Switches:** Instances where two passing two-wheelers swap IDs.

---

## 8. Readiness for Civil Engineering Analysis

```
+------------------------------------+--------------------------+-------------------------------------------------------------+
| Civil Engineering Metric           | Readiness Status         | Required Downstream Upgrades Before Analysis                |
+------------------------------------+--------------------------+-------------------------------------------------------------+
| 1. Vehicle Trajectories            | READY FOR PHASE 04       | Phase 04 must preserve gaps and handle two-frame latency.   |
+------------------------------------+--------------------------+-------------------------------------------------------------+
| 2. Screenline Vehicle Counts       | NOT READY FROM RAW TRACKS| Summing distinct track IDs will OVERCOUNT due to track      |
|                                    |                          | fragmentation. Phase 06 must count line-crossing events.    |
+------------------------------------+--------------------------+-------------------------------------------------------------+
| 3. Turning Movements (O-D)         | CONDITIONAL (PHASE 06)   | Requires zone-pair spatial intersection logic. Broken       |
|                                    |                          | trajectories must yield movement='unknown'.                 |
+------------------------------------+--------------------------+-------------------------------------------------------------+
| 4. Vehicle Class Allocation        | CONDITIONAL (PHASE 06)   | Track observations exhibit class jitter. Must apply track-  |
|                                    |                          | level majority voting before reporting class volume.        |
+------------------------------------+--------------------------+-------------------------------------------------------------+
| 5. Speed Estimation (km/h)         | STRICTLY BLOCKED         | Blocked until Phase 07 accepted planar homography and held- |
|                                    |                          | out GCP validation are complete.                            |
+------------------------------------+--------------------------+-------------------------------------------------------------+
| 6. Metric Queue Length (Metres)    | STRICTLY BLOCKED         | Blocked until surveyed stopline coordinates and calibrated  |
|                                    |                          | world grid are bound to queue zone.                         |
+------------------------------------+--------------------------+-------------------------------------------------------------+
```

---

## 9. Prioritised Correction Plan

Before Phase 04 and Phase 06 development, the following improvements should be scheduled:

### Priority 1: Implement True ID-Switch Detection (High)
* **Location:** [`backend/tracking.py`](file:///D:/Work/Personal/traffic-vision-final-year-project/backend/tracking.py#L128)
* **Action:** Compare matched track spatial trajectories and class consistency between consecutive frames to detect and increment `self._id_switches`.
* **Acceptance Criteria:** A synthetic test simulating two crossing tracks swapping bounding boxes records `id_switches >= 1`.

### Priority 2: Add Trajectory-Level Class Consensus Helper (High)
* **Location:** [`backend/tracking.py`](file:///D:/Work/Personal/traffic-vision-final-year-project/backend/tracking.py)
* **Action:** Provide a helper `resolve_track_class(observations)` that computes the modal (majority vote) or highest-confidence class across all observations of a `track_id`.
* **Acceptance Criteria:** A track with 5 `car` observations and 1 jittered `truck` observation resolves deterministically to `car`.

### Priority 3: Chunked Stream Persistence for Observations (Medium)
* **Location:** [`backend/services/tracking.py`](file:///D:/Work/Personal/traffic-vision-final-year-project/backend/services/tracking.py#L130-L168)
* **Action:** Flush `all_observations` in configurable batches (e.g. every 500 frames) instead of accumulating the entire video in RAM.
* **Acceptance Criteria:** Memory usage remains $O(B)$ bounded where $B$ is batch size.

---

## 10. Phase 04 Readiness Decision

### **Decision: PROCEED TO PHASE 04 (CONDITIONAL)**

Phase 04 (`Trajectories and Visualization`) is **authorized to proceed** under the following conditions:
1. Phase 04 must consume existing `tracks` rows and compute ordered trajectory histories ordered by `(run_id, track_id, frame_number)`.
2. Phase 04 must handle the two-frame confirmation latency (tracks beginning at frame $K+1$) without inventing retroactive points.
3. Phase 04 must treat bottom-centre points as image pixels and must not attempt world coordinate conversions.
4. Priority 1 and Priority 2 corrections should be committed alongside Phase 04 trajectory processing.
