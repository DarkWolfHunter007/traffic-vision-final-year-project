# Phase 04 Handoff — Trajectories & Visualization (Remediated v1.0.2)

## 1. Delivered Interfaces and Modules

### Trajectory Aggregation & Geometry (`backend.trajectories`)
- `compute_ground_point(x1, y1, x2, y2, method="bottom_center")`: Calculates the bottom-centre ground contact point `((x1 + x2) / 2.0, y2)`. Validates coordinates for finiteness and ordering (`x1 <= x2`, `y1 <= y2`). Strictly rejects bounding-box centre coordinates or unsupported methods.
- `is_near_boundary(x1, y1, x2, y2, width, height, margin_px=20.0)`: Checks if a bounding box intersects the outer boundary margin of a video frame.
- `TrajectoryPoint`: Immutable observation dataclass storing `frame_number`, `timestamp_s`, `ground_x`, `ground_y`, `x1`, `y1`, `x2`, `y2`, and optional `confidence` and `vehicle_class`.
- `Trajectory`: Chronological trajectory history for a tracked vehicle storing `run_id`, `video_id`, `track_id`, `points`, `consensus_class`, `status`, `status_reason`, `missing_frames_count`, `duration_s`, `is_incomplete`, `diagnostics`, `lifecycle`, `continuity`, and `termination_reason`.
  - Properties & methods: `start_frame`, `end_frame`, `start_timestamp_s`, `end_timestamp_s`, `trail_points(max_length=None)`, `point_at_frame(frame_number)`.
- `build_trajectories(observations, video_width=None, video_height=None, last_video_frame=None, config=None, frame_stride=None)`: Groups observations by `track_id` for a single `run_id` (rejecting mixed runs), orders them chronologically by `(frame_number ASC, timestamp_s ASC)`, computes deterministic consensus vehicle class (via `resolve_track_class`), detects missing frame intervals and temporal gaps using stride-aware accounting, and classifies continuity and lifecycle.

### Visualization Engine (`backend.visualization`)
- `VisualizationConfig`: Dataclass of rendering toggles: `show_boxes`, `show_labels`, `show_confidences`, `show_ids`, `show_trails`, `trail_length`, `trail_thickness`, `box_thickness`, `font_scale`, `draw_ground_point`, `ground_point_radius`, `max_trail_gap_seconds` (default 1.0s), and `max_trail_gap_frames`.
- `get_track_color(track_id)`: Deterministic RGB color assignment from a 20-color high-contrast palette.
- `render_frame_annotations(image, frame_number, tracks, config=None)`: Renders bounding boxes, consensus class labels, confidences, track IDs, segmented motion trails (breaking lines across temporal gaps $> \text{max\_trail\_gap\_seconds}$), and bottom-centre ground markers on an image canvas without mutating the input array.

### Service Orchestration (`backend.services.visualization` & `backend.services.tracking`)
- `build_run_trajectories(connection, run_id, config=None)`: Queries stored tracks from SQLite for `run_id`, determines `frame_stride` from config or run lineage, and constructs `Trajectory` instances.
- `render_preview_visualization(parent_run_id, frame_number, config, repository_root, output_path=None)`: Decodes a single requested video frame, annotates active tracks, and saves a JPEG/PNG image. Validates `frame_number >= 0`.
- `render_video_visualization(parent_run_id, config, repository_root, output_path=None, start_frame=None, end_frame=None)`: Decodes video frames, overlays trajectories, writes an annotated MP4 video atomically via temporary files, records a new child `processing_runs` record with full provenance, and handles interruptions safely. Validates frame ranges and prevents zero-frame completed runs.
- `run_tracking(parent_run_id, config, repository_root, tracker=None)`: Streams frames and detections in bounded window chunks (`frame_number BETWEEN chunk_start AND chunk_end`), guaranteeing $O(\text{batch\_size})$ memory usage regardless of video duration.

### CLI Command (`backend.cli`)
- `traffic-vision visualize PARENT_RUN_ID [--output OUTPUT] [--preview-frame FRAME] [--start-frame START] [--end-frame END] [--config CONFIG]`: Command-line interface with validated frame ranges for generating visualization previews or annotated MP4 videos.

---

## 2. Configuration Keys and Defaults

Added to `configs/default.yaml` and validated in `backend/config.py`:

```yaml
tracking:
  chunk_frames: 500                   # Streaming window batch chunk size (default 500 frames)

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
  max_trail_gap_seconds: 1.0          # Maximum gap before trail breaks into disjoint segment
  output_dir: data/processed/visualizations
```

---

## 3. Trajectory Status & Lifecycle Semantics

Status values strictly enforce the database check constraint `CHECK (trajectory_status IN ('active', 'complete', 'fragmented', 'invalid'))` while decoupling track lifecycle from continuity quality:

| Status | Lifecycle | Continuity | Termination Reason | Description |
|---|---|---|---|---|
| `active` | `active` | `continuous` | `video_end` | Track observed on final video frame without observation gaps. Vehicle traversal incomplete at video boundary. |
| `complete` | `ended` | `continuous` | `boundary_exit` | Track spans a continuous sequence without internal gaps exceeding `max_gap_seconds`, exiting near the frame boundary. |
| `fragmented` | `active` | `discontinuous` | `video_end` | Track has observation gap(s) $> \text{max\_gap\_seconds}$ but was observed on the final frame. (Internal gap takes precedence over final frame presence). |
| `fragmented` | `ended` | `continuous` | `interior_termination` | Track terminated in scene interior without internal gaps. Disappearance indicates detector loss or occlusion; does not prove physical fragmentation. |
| `fragmented` | `ended` | `discontinuous` | `boundary_exit` or `interior_termination` | Track contains internal gaps and ended before video end. |
| `invalid` | `ended` | `invalid` | `invalid` | Malformed bounding boxes, corrupt stored coordinates, negative timestamps, or non-monotonic timestamps. |

---

## 4. Ground-Point Conventions & Coordinate Separation

- **Pixel Road Contact**: The bottom-centre point `(ground_x, ground_y) = ((x1 + x2) / 2.0, y2)` is computed on the 2D image plane.
- **Bounding Box Centre Prohibited**: The bounding box centre is explicitly rejected as the road-contact point because it projects above the physical ground plane for 3D vehicles (e.g., buses, auto-rickshaws, trucks).
- **Stored Coordinate Validation**: Stored ground coordinates in database records are checked against computed ground points within $10^{-3}$ tolerance. Corrupt values trigger `STATUS_INVALID`.
- **World Coordinate Invariant**: `world_x` and `world_y` remain strictly `NULL`. No camera calibration is applied or assumed in Phase 04.

---

## 5. Lineage and Failure Recovery Guarantees

- **Lineage**: Every video visualization run creates an immutable record in `processing_runs`:
  - `run_id`: UUID primary key.
  - `parent_run_id`: References the completed Phase 03 tracking run.
  - `video_id`, `source_video_sha256`, `model_version`: Inherited from upstream run.
  - `status`: `running` during rendering, transitioning to `completed` or `failed`.
- **Atomic File Writing**: Video rendering writes to a temporary file (`.tmp.mp4`) and renames it atomically to the final destination upon completion.
- **Zero-Frame Protection**: If rendering produces 0 frames (e.g. range outside video), the temporary file is unlinked, a `RuntimeError` is raised, and the run status is recorded as `"failed"`.
- **Interruption Recovery**: If rendering is interrupted, `.tmp.mp4` is unlinked immediately and run status is updated to `"failed"` with the error stack trace logged in `notes`.
- **Bounded Tracking Memory**: `run_tracking` queries `video_frames` and `detections` in bounded window chunks of `batch_size`, preventing memory exhaustion on long CCTV videos.

---

## 6. Test Suite and Evidence

The entire test regression suite passes with 76 total tests:

```text
uv run pytest -v
============================= 76 passed in 12.28s =============================
```

Focused test files:
- `tests/test_phase_04_audit.py` (18 tests):
  - Cross-run track ID collision rejection (`ValueError`).
  - Active status precedence over internal gaps (`status=fragmented`, `lifecycle=active`).
  - Motion trail gap breaking (no bridges drawn across multi-second gaps).
  - Short continuous trail rendering.
  - Intentional frame stride trail continuity.
  - Trajectory trail segmentation around gaps.
  - Zero-area bounding box handling.
  - Stride-aware gap accounting (`missing_frames_count` equals missed expected samples).
  - Corrupt stored ground coordinates rejection (`status=invalid`).
  - Negative and non-finite timestamps rejection (`status=invalid`).
  - Interior termination semantics and uncertainty diagnostics.
  - Visualization frame range validation (`start_frame`, `end_frame`, `preview_frame`).
  - **T2**: Single-frame range visualization (`start_frame == end_frame` renders exactly 1 frame, status completed).
  - **T3**: Exact trail gap boundary joining ($\le 1.0s$ / $\le 10$ frames) vs splitting ($> 1.0s$ / $> 10$ frames).
  - **T3**: Large frame stride spacing ($\Delta t > 1.0s$) splitting trails across all consecutive samples.
  - **T4**: Ground-point tolerance acceptance ($\le 0.0009$) vs rejection ($\ge 0.0011$) for $x$ and $y$ independently.
  - **T5**: Interior termination margin classification at `margin_px = 20.0` (`boundary_exit`), inside (`boundary_exit`), and outside (`interior_termination`).
  - **T6**: Stride off-grid gap accounting under current `round(fn_gap / stride)` behavior (gaps 7, 8, 12).
- `tests/test_trajectories.py` (14 tests):
  - Bottom-centre coordinate calculation.
  - Rejection of bbox centre and invalid methods.
  - Rejection of malformed coordinates (NaN, inf, inverted boxes).
  - Deterministic chronological ordering.
  - Preservation of raw observations without interpolation.
  - Class consensus integration with Phase 03 voting helper.
  - Trajectory status classification (`active`, `complete`, `fragmented`, `invalid`).
  - Handling of empty observations and trail slicing helpers.
- `tests/test_visualization.py` (13 tests):
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
  - Zero-frame video visualization failure and cleanup.
  - CLI visualize argument validation (`--start-frame`, `--end-frame`, `--preview-frame`).
- `tests/test_tracking_service.py` (6 tests):
  - Canonical track persistence.
  - Bounded memory batch persistence.
  - Atomic rollback on database failure.
  - Missing/incomplete parent run rejection.
  - Windowed chunk streaming across chunk boundaries.
  - **T1**: Multi-chunk streaming consistency across chunk boundaries with `chunk_frames = 3` on $\ge 12$ frame video matching `chunk_frames = 500`.

---

## 7. Known Limitations & Assumptions

- **Track Status in DB**: `tracks.trajectory_status` is always the placeholder `'complete'` in the DB and real status must come from `build_trajectories()`. Downstream consumers must not query or rely on `tracks.trajectory_status` directly from the database.
- **GPU OOM Behavior**: `gpu_oom_behavior` in `configs/default.yaml` is a placeholder not implemented.
- **Software Fixtures**: Synthetic fixtures validate geometric invariants, memory streaming, and error handling. Real Pattom CCTV footage will be ingested in field validation.
- **Physical vs Diagnostic Fragmentation**: Temporal gaps and interior disappearances are heuristics for potential fragmentation. Physical identity switches cannot be proven without manual ground truth.
- **Occlusion Trail Continuity**: Trajectory trails only connect observed points; they do not draw synthetic interpolation lines across missing frames.

---

## 8. Dependencies for Phase 05 & Phase 06

- Phase 05 (ROI, Zones, Counting Lines) consumes the bottom-centre ground points `(ground_x, ground_y)` and ordered trajectory histories `points` produced by `backend.trajectories.build_trajectories()`.
- Phase 06 (Vehicle Counting & Movements) relies on `consensus_class`, `lifecycle`, `continuity`, and trajectory statuses (`complete`, `active`, `fragmented`) to perform movement classification and filter spurious tracks.
