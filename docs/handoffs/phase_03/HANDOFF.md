# Phase 03 Handoff — ByteTrack Integration & Tracker Lifecycle

## Delivered interfaces

- `backend.tracking.cadence_to_frames(buffer_seconds, fps, frame_stride)`: converts time duration in seconds into integer frames based on effective processing cadence.
- `backend.tracking.DetectionBatch`: NumPy-backed detection adapter providing `xywh`, `conf`, `cls`, and boolean indexing for direct consumption by Ultralytics `BYTETracker`.
- `backend.tracking.ByteTrackerAdapter`: standalone ByteTrack adapter that wraps `ultralytics.trackers.byte_tracker.BYTETracker` directly. It never calls `model.track()`. Exposes `metrics.id_switches = None` (explicitly unmeasured without ground truth).
- `backend.tracking.evaluate_id_switches(ground_truth_assignments)`: evaluates true CLEAR MOT identity switches against ground-truth association tuples `(frame, gt_id, predicted_track_id)`.
- `backend.tracking.resolve_track_class(observations, min_confidence=0.0, fallback_class="unknown")`: derives a deterministic, consensus vehicle class per track via confidence-weighted voting with alphabetical tie-breaking, leaving raw per-frame observations intact.
- `backend.services.tracking.run_tracking(parent_run_id, config, repository_root, tracker=None)`: creates an immutable child tracking run, processes detections frame-by-frame, and persists canonical track observations to the `tracks` SQLite table using bounded-memory streaming batches.
- `traffic-vision track PARENT_RUN_ID --config CONFIG`: CLI entry point for running ByteTrack tracking on completed Phase 02 detection runs.

## Configuration keys

The following configuration parameters are captured in `configs/default.yaml` and recorded in each run's immutable configuration snapshot and hash:

```yaml
tracking:
  tracker_type: bytetrack
  track_high_thresh: 0.5
  track_low_thresh: 0.1
  new_track_thresh: 0.6
  match_thresh: 0.8
  track_buffer_seconds: 1.0  # Buffer duration in seconds (converted to frames based on effective fps)
  fuse_score: true
  batch_size: 500            # Bounded memory observation persistence chunk size
```

## Schema changes and data contract

No schema alterations were required. The canonical `tracks` table defined in `backend/database/schema.sql` was populated directly:
- `track_observation_id`: UUID primary key.
- `run_id`: immutable tracking run ID referencing `processing_runs(run_id)`.
- `parent_run_id`: explicitly links the tracking run to the Phase 02 detection parent run.
- `video_id`: propagated from parent video provenance.
- `track_id`: persistent integer track ID assigned by ByteTrack.
- `frame_number`, `timestamp_s`: authoritative decoder PTS propagated from parent detections.
- `vehicle_class`, `confidence`: mapped canonical class name and score.
- `x1`, `y1`, `x2`, `y2`: Kalman filter updated bounding box coordinates.
- `ground_x`, `ground_y`: bottom-centre road contact point `((x1 + x2) / 2, y2)`.
- `world_x`, `world_y`: `NULL` (calibration excluded in Phase 03).
- `calibration_id`: `NULL` (calibration excluded in Phase 03).
- `trajectory_status`: `'complete'` (enforces check constraint `IN ('active', 'complete', 'fragmented', 'invalid')`).

## Memory & transaction reliability

- Bounded RAM: Observations are queued in memory only up to `batch_size` (default 500) before flushing to SQLite.
- Atomic Rollback: All batch flushes occur within a single database transaction context. If an error occurs during any batch, the entire transaction is rolled back, leaving zero orphaned rows in `tracks`, and the run is recorded with `status = 'failed'`.

## Tests and software fixtures

```text
uv run pytest -v
29 passed in 4.12s
```

Test coverage includes:
1. `tests/test_tracking.py`:
   - Cadence-to-frame conversion across varying nominal FPS (15, 25, 30) and frame strides (1, 2, 3).
   - DetectionBatch slicing, `xywh` conversion, and empty-batch properties.
   - Persistent ID association across consecutive frames for moving targets.
   - Graceful handling of empty frames without crashing the tracker.
   - Track continuity preservation across temporary missed detections within the buffer window.
   - Unlabelled video metric reporting: asserts `metrics.id_switches is None` (unmeasured).
   - `evaluate_id_switches`: verified on known switch (crossing targets) and known no-switch cases.
   - `resolve_track_class`: verified majority voting (5 cars + 1 truck -> car), non-mutation of raw classes, deterministic tie-breaking, and empty/low-confidence handling.
2. `tests/test_tracking_service.py`:
   - End-to-end integration across Phase 01 ingestion -> Phase 02 detection -> Phase 03 tracking.
   - Verification of parent-child run lineage, status completion, and notes logging with `id_switches=unmeasured`.
   - Verification of `tracks` table persistence, column integrity, bottom-centre calculation, and `NULL` world coordinates.
   - Rejection of invalid, missing, or incomplete parent runs.
   - Bounded memory batch persistence across multiple chunk flushes.
   - Atomic rollback verification upon simulated database failure during later batches.

## Assumptions and limitations

- CPU inference was validated; no hardware or GPU claims are made.
- Synthetic media fixtures were used for automated testing. No actual Pattom CCTV footage is included or altered.
- Tracking accuracy under heavy mixed-traffic occlusions at Pattom Junction remains unvalidated pending real footage and manual ground-truth baseline evaluation.
- Phase 03 strictly isolates tracking from downstream analytics.

## Next phase dependencies (Phase 04)

- Phase 04 may consume canonical `tracks` to build ordered trajectory histories and render trajectory visualizations.
- Phase 04 must preserve the bottom-centre ground point convention and retain complete lineage provenance.
- Phase 04 must use `resolve_track_class` for trajectory-level label display while keeping raw observation labels intact.
