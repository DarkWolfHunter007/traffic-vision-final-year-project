# Phase 04 Validation Report — Trajectories & Visualization

**Auditor Role:** Senior Computer-Vision Engineer, Traffic-Engineering Methodologist, and Database Reliability Engineer  
**Branch:** `antigravity/v1.0.2`  
**Base Commit:** `7556381` (`feat: complete Phase 03 ByteTrack integration and remediation`)  
**Scope:** Phase 04 — Trajectories and Visualization (`prompts/phase_04_trajectories_and_visualization.md`)  
**Status:** IMPLEMENTED AND TEST-VERIFIED (Subject to independent review)

---

## 1. Files Changed and Interfaces Added

| Component | File | Action | Purpose / Responsibility |
|---|---|---|---|
| **Trajectory Engine** | `backend/trajectories.py` | NEW | Aggregation of ordered trajectory points by `(run_id, track_id)`, bottom-centre ground point calculation, class consensus integration, missing frame accounting, and continuity status classification (`active`, `complete`, `fragmented`, `invalid`). |
| **Visualization Engine** | `backend/visualization.py` | NEW | Deterministic rendering of bounding boxes, consensus class labels, detection confidences, track IDs, motion trails, and ground-contact markers onto image frames. Independent overlay toggles and deterministic palette. |
| **Service Layer** | `backend/services/visualization.py` | NEW | Trajectory assembly from SQLite, single preview frame rendering, and video rendering orchestration with atomic temporary file management and `processing_runs` lineage persistence. |
| **Repository Queries** | `backend/database/repository.py` | MODIFIED | Added `fetch_tracks_for_run`, `fetch_tracks_for_frame`, and `fetch_run_by_id`. |
| **Configuration** | `backend/config.py`, `configs/default.yaml` | MODIFIED | Added `trajectories` and `visualization` configuration sections with schema validation rules. |
| **CLI** | `backend/cli.py` | MODIFIED | Added `traffic-vision visualize` subcommand with support for `--output`, `--preview-frame`, `--start-frame`, and `--end-frame`. |
| **Test Suites** | `tests/test_trajectories.py`, `tests/test_visualization.py` | NEW | 25 focused unit and integration tests covering geometry invariants, status semantics, deterministic rendering, database lineage, and interruption cleanup. |
| **Handoff** | `docs/handoffs/phase_04/HANDOFF.md` | NEW | Phase 04 contracts, interfaces, configuration keys, and downstream dependencies. |

---

## 2. Trajectory Ordering and Status Semantics

### Deterministic Ordering
Observations fetched from the `tracks` table are grouped by `track_id` and deterministically sorted using a composite tuple key:
$$\text{key} = (\text{frame\_number}, \text{timestamp\_s})$$
- Source frame numbers and decoder presentation timestamps (PTS in seconds) are preserved identically from upstream Phase 01/03 tables.
- **No Interpolation**: Missing frames between non-consecutive observations are accurately counted in `missing_frames_count` and listed in `diagnostics["internal_gaps"]`, but no synthetic intermediate points are invented.

### Status Definitions
Statuses comply strictly with the schema check constraint `CHECK (trajectory_status IN ('active', 'complete', 'fragmented', 'invalid'))`:
1. **`active`**: The tracked vehicle was observed on the final frame of the video sequence or processing window (`frame_number >= last_video_frame`). The track did not terminate; the observation window ended.
2. **`complete`**: The vehicle's trajectory concluded without prolonged temporal gaps ($> \text{max\_gap\_seconds}$), either exiting near a designated frame boundary ($\le \text{boundary\_margin\_px}$) or terminating naturally without abrupt interruption.
3. **`fragmented`**: The trajectory shows evidence of tracking discontinuity:
   - Contains internal observation gaps exceeding `max_gap_seconds` (default $1.0\,\text{s}$).
   - Disappeared abruptly in the interior of the scene without reaching the frame boundary.
   - *Diagnostic Disclaimer*: Flagged as suspected fragmentation in `diagnostics["uncertainty_note"]` to acknowledge that temporal gaps may stem from occlusion, missed detections, or lighting changes, and physical identity fragmentation cannot be proved without ground truth.
4. **`invalid`**: The track observations fail data validation invariants:
   - Malformed bounding box ($x_1 > x_2$, $y_1 > y_2$, or non-finite values).
   - Inverted/non-monotonic timestamps ($t_{i+1} < t_i$).
   - Duplicate observations for the same frame ($F_{i+1} = F_i$).
   - Conflicting `run_id` or `video_id` in the track group.

---

## 3. Ground-Point Coordinate Conventions

- **Road Surface Projection**:
  $$\text{ground\_x} = \frac{x_1 + x_2}{2.0}, \quad \text{ground\_y} = y_2$$
- **Bounding Box Centre Prohibited**: The bounding box centre $(\frac{x_1 + x_2}{2}, \frac{y_1 + y_2}{2})$ is strictly rejected for physical road contact. In CCTV oblique views, the geometric centre rests above the road surface, introducing large elevation-induced parallax errors for high-profile vehicles (buses, trucks, auto-rickshaws).
- **Pixel vs Calibrated World Coordinates**: Pixel coordinates `(ground_x, ground_y)` are kept strictly distinct from metric world coordinates `(world_x, world_y)`. World coordinates remain `NULL` until Phase 07 homography calibration is established.

---

## 4. Visualization Behaviour and Configuration

The visualization engine (`backend/visualization.py`) provides pure, deterministic frame annotation:
- **Colour Palette**: A 20-colour high-contrast palette assigns a stable, repeatable RGB colour based on `abs(track_id) % 20`.
- **Motion Trails**: Polyline rendered connecting past `(ground_x, ground_y)` contact points up to `trail_length` (default 30 observations).
- **Independent Toggles**:
  - `show_boxes`: Enables/disables bounding box rectangles.
  - `show_labels`: Enables/disables vehicle class tags (using track consensus class).
  - `show_confidences`: Enables/disables floating-point confidence score display.
  - `show_ids`: Enables/disables `#<track_id>` display.
  - `show_trails`: Enables/disables ground-point motion trail polylines.
  - `draw_ground_point`: Draws a distinct marker at `(ground_x, ground_y)` on the road plane.
- **Robustness**: Handles empty tracks, single-point tracks, out-of-bounds coordinates, and malformed boxes safely without throwing uncaught exceptions.

---

## 5. Database Lineage and Failure Recovery Guarantees

### Lineage
When generating video visualizations, a child processing run is registered in SQLite:
- `run_id`: UUIDv4 primary key.
- `parent_run_id`: Points to the completed Phase 03 tracking run.
- `video_id`: Inherited from upstream run.
- `source_video_sha256`: Verified against source media.
- `config_hash`, `config_json`: Captures visualization and trajectory configuration snapshot.
- `code_version`: Git commit SHA.
- `status`: Transitions from `running` to `completed` upon completion, or `failed` on error.
- `notes`: Stores output path, rendered frame count, and trajectory count.

### Atomic Writing & Crash Recovery
- Video rendering writes to a temporary file (`<target_stem>.tmp.mp4`).
- Upon clean loop completion, the temporary file is atomically replaced to the target destination path.
- In the event of an interruption, power failure, or exception:
  - Any open VideoWriter handle is released.
  - The incomplete `.tmp.mp4` file is immediately unlinked.
  - The `processing_runs` row is updated to `status = 'failed'` with the error details recorded in `notes`.
  - Zero partially rendered files remain on disk.

---

## 6. Tests Executed and Actual Results

All tests pass cleanly in the virtual environment (`Python 3.12.13`, `Windows AMD64`):

```text
uv run pytest -v
============================= 54 passed in 5.25s ==============================
```

Breakdown of tests:
- **Phase 01 Tests** (`test_app.py`, `test_config.py`, `test_database.py`, `test_ingestion.py`, `test_media.py`): 11 tests passed.
- **Phase 02 Tests** (`test_detection.py`, `test_detection_service.py`): 5 tests passed.
- **Phase 03 Tests** (`test_tracking.py`, `test_tracking_service.py`): 13 tests passed.
- **Phase 04 Trajectory Tests** (`test_trajectories.py`): 14 tests passed.
- **Phase 04 Visualization Tests** (`test_visualization.py`): 11 tests passed.

**Total Test Count:** 54 passing tests.

---

## 7. Known Limitations and Unresolved Issues

1. **Synthetic Software Fixtures**: All tests currently execute against synthetic video files and mock database rows. Ingestion and validation against actual recorded CCTV footage from Pattom Intersection remains a pending project milestone.
2. **Physical Continuity Ambiguity**: The system marks tracks with temporal gaps $> 1.0\,\text{s}$ as `fragmented`, but cannot distinguish true physical re-identification failure from prolonged occlusion by buses or roadside structures without manual review (Phase 10).
3. **No 3D Elevation Compensation**: Bounding box bottom-centre provides a standard road-contact approximation, but on steep slopes or elevated flyovers, road surface pitch can introduce subtle planar distortions prior to Phase 07 homography calibration.

---

## 8. Downstream Dependencies (Phases 05 & 06)

- **Phase 05 (ROI & Counting Lines)**:
  - Consumes `Trajectory.trail_points()` and `TrajectoryPoint.ground_x / ground_y` to compute spatial geometric intersections with counting lines and polygon entry/exit zones.
- **Phase 06 (Vehicle Counting & Turning Movement Classification)**:
  - Consumes `Trajectory.consensus_class` to produce class-stratified vehicle counts.
  - Consumes `Trajectory.status` to exclude `invalid` or severely fragmented partial tracks from 15-minute volume binning.
