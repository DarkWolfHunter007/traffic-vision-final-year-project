# Phase 04 Handoff — Trajectories & Visualization

## 1. Delivered Interfaces and Modules

### Trajectory Aggregation & Geometry (`backend.trajectories`)
- `compute_ground_point(x1, y1, x2, y2, method="bottom_center")`: Calculates the bottom-centre ground contact point `((x1 + x2) / 2.0, y2)`. Validates coordinates for finiteness and ordering (`x1 <= x2`, `y1 <= y2`). Strictly rejects bounding-box centre coordinates or unsupported methods.
- `is_near_boundary(x1, y1, x2, y2, width, height, margin_px=20.0)`: Checks if a bounding box intersects the outer boundary margin of a video frame.
- `TrajectoryPoint`: Immutable observation dataclass storing `frame_number`, `timestamp_s`, `ground_x`, `ground_y`, `x1`, `y1`, `x2`, `y2`, and optional `confidence` and `vehicle_class`.
- `Trajectory`: Chronological trajectory history for a tracked vehicle storing `run_id`, `video_id`, `track_id`, `points`, `consensus_class`, `status`, `status_reason`, `missing_frames_count`, `duration_s`, `is_incomplete`, and `diagnostics`.
  - Properties & methods: `start_frame`, `end_frame`, `start_timestamp_s`, `end_timestamp_s`, `trail_points(max_length=None)`, `point_at_frame(frame_number)`.
- `build_trajectories(observations, video_width=None, video_height=None, last_video_frame=None, config=None)`: Groups observations by `track_id`, orders them chronologically by `(frame_number ASC, timestamp_s ASC)`, computes deterministic consensus vehicle class (via `resolve_track_class`), detects missing frame intervals and temporal gaps, and classifies continuity into `active`, `complete`, `fragmented`, or `invalid`.

### Visualization Engine (`backend.visualization`)
- `VisualizationConfig`: Dataclass of rendering toggles: `show_boxes`, `show_labels`, `show_confidences`, `show_ids`, `show_trails`, `trail_length`, `trail_thickness`, `box_thickness`, `font_scale`, `draw_ground_point`, `ground_point_radius`.
- `get_track_color(track_id)`: Deterministic RGB color assignment from a 20-color high-contrast palette.
- `render_frame_annotations(image, frame_number, tracks, config=None)`: Renders bounding boxes, consensus class labels, confidences, track IDs, motion trails, and bottom-centre ground markers on an image canvas without mutating the input array.

### Service Orchestration (`backend.services.visualization`)
- `build_run_trajectories(connection, run_id, config=None)`: Queries stored tracks from SQLite for `run_id` and constructs `Trajectory` instances.
- `render_preview_visualization(parent_run_id, frame_number, config, repository_root, output_path=None)`: Decodes a single requested video frame, annotates active tracks, and saves a JPEG/PNG image.
- `render_video_visualization(parent_run_id, config, repository_root, output_path=None, start_frame=None, end_frame=None)`: Decodes video frames, overlays trajectories, writes an annotated MP4 video atomically via temporary files, records a new child `processing_runs` record with full provenance, and handles interruptions safely.

### CLI Command (`backend.cli`)
- `traffic-vision visualize PARENT_RUN_ID [--output OUTPUT] [--preview-frame FRAME] [--start-frame START] [--end-frame END] [--config CONFIG]`: Command-line interface for generating visualization previews or annotated MP4 videos.

---

## 2. Configuration Keys and Defaults

Added to `configs/default.yaml` and validated in `backend/config.py`:

```yaml
trajectories:
  ground_point_method: bottom_center  # Civil engineering road-surface contact point
  max_gap_seconds: 1.0                # Gap threshold beyond which fragmentation is suspected
  min_track_length_frames: 3          # Tracks shorter than this are flagged as incomplete
  boundary_margin_px: 20              # Margin from frame edge to identify normal scene exit

visualization:
  enabled: true
  show_boxes: true
  show_labels: true
  show_confidences: true
  show_ids: true
  show_trails: true
  trail_length: 30                    # Maximum past ground points in motion trail
  trail_thickness: 2
  box_thickness: 2
  font_scale: 0.5
  output_dir: data/processed/visualizations
```

---

## 3. Trajectory Status Semantics

Status values strictly enforce the database check constraint `CHECK (trajectory_status IN ('active', 'complete', 'fragmented', 'invalid'))`:

| Status | Exact Definition | Diagnostic Details |
|---|---|---|
| `active` | Track was observed on the final frame of the video sequence or processing segment (`frame_number >= last_video_frame`). The vehicle has not yet completed its traversal. | `is_incomplete = True`, `status_reason = "Track remains active on final video frame"` |
| `complete` | Track spans a continuous sequence without internal gaps exceeding `max_gap_seconds`, and either exited near a frame boundary (`margin <= 20px`) or terminated naturally. | `is_incomplete = False`, `status_reason = "Track completed normally"` |
| `fragmented` | Suspected tracking discontinuity where internal observations have a gap $> \text{max\_gap\_seconds}$, or the track terminated abruptly in the interior of the scene without reaching the frame boundary. | `is_incomplete = True`, records internal gaps and boundary status; exposes uncertainty note. |
| `invalid` | Observations contain malformed bounding box coordinates (`x1 > x2`, `y1 > y2`, NaN/inf), non-monotonic timestamps, or duplicate observations on the same frame. | `is_incomplete = True`, `status_reason` documents exact violation. |

---

## 4. Ground-Point Conventions & Coordinate Separation

- **Pixel Road Contact**: The bottom-centre point `(ground_x, ground_y) = ((x1 + x2) / 2.0, y2)` is computed on the 2D image plane.
- **Bounding Box Centre Prohibited**: The bounding box centre is explicitly rejected as the road-contact point because it projects above the physical ground plane for 3D vehicles (e.g., buses, auto-rickshaws, trucks).
- **World Coordinate Invariant**: `world_x` and `world_y` remain strictly `NULL`. No camera calibration is applied or assumed in Phase 04.

---

## 5. Lineage and Failure Recovery Guarantees

- **Lineage**: Every video visualization run creates an immutable record in `processing_runs`:
  - `run_id`: UUID primary key.
  - `parent_run_id`: References the completed Phase 03 tracking run.
  - `video_id`, `source_video_sha256`, `model_version`: Inherited from upstream run.
  - `status`: `running` during rendering, transitioning to `completed` or `failed`.
- **Atomic File Writing**: Video rendering writes to a temporary file (`.tmp.mp4`) and renames it atomically to the final destination upon completion. If rendering is interrupted or errors occur:
  - The temporary `.tmp.mp4` file is unlinked immediately.
  - The database run status is updated to `"failed"` with the error stack trace logged in `notes`.
  - Upstream tables (`videos`, `video_frames`, `detections`, `tracks`) are read-only and never mutated.

---

## 6. Test Suite and Evidence

The entire test regression suite passes with 54 total tests (25 new tests added in Phase 04):

```text
uv run pytest -v
============================= 54 passed in 5.25s ==============================
```

Focused test files:
- `tests/test_trajectories.py` (14 tests):
  - Bottom-centre coordinate calculation.
  - Rejection of bbox centre and invalid methods.
  - Rejection of malformed coordinates (NaN, inf, inverted boxes).
  - Deterministic chronological ordering.
  - Preservation of raw observations without interpolation.
  - Class consensus integration with Phase 03 voting helper.
  - Trajectory status classification (`active`, `complete`, `fragmented`, `invalid`).
  - Handling of empty observations and trail slicing helpers.
- `tests/test_visualization.py` (11 tests):
  - Configuration parsing and styling overrides.
  - Deterministic colour palette.
  - Deterministic image annotation (bit-exact array equality).
  - Overlay toggles for boxes, labels, IDs, and motion trails.
  - Empty tracks handling without image alteration.
  - Safe handling of out-of-bounds or clipped boxes.
  - Database service integration (`build_run_trajectories`).
  - Single preview frame generation (`render_preview_visualization`).
  - Video rendering lineage and notes recording (`render_video_visualization`).
  - Rejection of nonexistent or incomplete parent runs.
  - Failure cleanup and status update on simulated crash.

---

## 7. Assumptions & Known Limitations

- **Software Fixtures**: All tests utilize synthetic video and observation fixtures. Real Pattom CCTV clips have not yet been ingested for validation.
- **Physical vs Diagnostic Fragmentation**: Temporal gaps and interior disappearances are heuristics for potential fragmentation. Physical identity switches cannot be proven without manual ground truth.
- **Occlusion Trail Continuity**: Trajectory trails only connect observed points; they do not draw synthetic interpolation lines across missing frames.

---

## 8. Dependencies for Phase 05 & Phase 06

- Phase 05 (ROI, Zones, Counting Lines) consumes the bottom-centre ground points `(ground_x, ground_y)` and ordered trajectory histories `points` produced by `backend.trajectories.build_trajectories()`.
- Phase 06 (Vehicle Counting & Movements) relies on `consensus_class` and trajectory continuity statuses (`complete`, `active`, `fragmented`) to perform movement classification and filter spurious tracks.
