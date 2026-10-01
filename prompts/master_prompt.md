# Traffic Vision — Master Reference Specification

## Instruction to the implementation model

**Implement nothing except the phase you are given.**

This file is the authoritative project context and architecture reference. It is not a request to implement the whole application. When executing a phase prompt, use this document only to understand shared requirements and interfaces, then implement only the explicitly assigned phase.

Independent prompt checking, implementation review, testing review, and completion verification are performed by separate Pro subagents. The implementation model must run its own phase tests and report raw results, but must not declare the phase accepted.

## 1. Project context

Traffic Vision is an offline computer-vision/data-collection subsystem for a final-year Civil Engineering study of Pattom Intersection, Thiruvananthapuram, Kerala.

Research pipeline:

```
CCTV → Detection → Tracking → Vehicle-level traffic data
     → downstream congestion/emission analysis → redesign/MCE/SUMO
```

This repository stops at reliable, traceable traffic-data extraction. Final congestion methodology, emission modelling, MCE, redesign generation, and SUMO simulation are outside scope.

## 2. Shared technology

Python 3.12, Ultralytics YOLO, PyTorch, OpenCV, ByteTrack, NumPy, Pandas, SQLite, FastAPI, React/TypeScript/Tailwind, and FFmpeg may be used where required. Dependencies must be introduced only when needed by the assigned phase.

## 3. Phase ownership

| Phase | Owns | Master sections |
|---|---|---|
| 01 | video ingestion, timestamps, preprocessing/scaffolding, config, DB bootstrap, logging | Video Input, Preprocessing, Configuration, Data Integrity |
| 02 | YOLO inference, tiled inference/merge, class mapping | Detection, Preprocessing |
| 03 | direct ByteTrack integration, lifecycle, ID-switch instrumentation | Tracking |
| 04 | trajectory history, ground point, visualization | Tracking, Visualization |
| 05 | ROI, entry/exit zones, counting-line geometry/configuration | ROI, Counting Lines, Approach/Movement Geometry |
| 06 | crossing events, movement derivation, ground-truth counting set, 15-minute bins | Counting, Validation |
| 07 | homography/calibration diagnostics | Calibration |
| 08 | calibrated speed observations | Speed |
| 09 | stopped vehicles and queue observations | Queue |
| 10 | uncertainty review, snippets, class and box correction | Manual Review |
| 11 | approved correction dataset and leakage-safe splits | Active Learning |
| 12 | model training/evaluation and tracking/counting validation | Model Improvement, Validation |
| 13 | exports, research summaries, dashboard | Export, Dashboard |

No phase may silently implement another phase's functionality.

## 4. Canonical data contract

The source of truth is:
- `backend/database/schema.sql`
- `docs/data_dictionary.md`

Do not create alternate field names in phase code or prompts.

Important canonical fields include:
- `video_id`
- `run_id`
- `frame_number`
- `timestamp_s`
- `queue_length_m`
- `corrected_class`
- `corrected_bbox_json`

Every derived/result table must carry `run_id`.

## 5. Provenance

A processing run represents one reproducible execution of a video with a specific model/configuration.

Every run records:
- source video SHA-256
- optional parent run ID
- model version when applicable
- complete configuration JSON snapshot
- configuration SHA-256
- schema version
- required Git code version SHA
- start/end time
- constrained status

Changing thresholds, frame selection, model weights, calibration, or relevant configuration creates a new run. A downstream-only run must use `parent_run_id` to reference reusable upstream results rather than forcing detection/tracking to run again. Results from different runs must never be mixed.

The `videos` table stores the source SHA-256. `processing_runs` stores the exact configuration snapshot, configuration hash, required Git code SHA, and lineage through `parent_run_id`.

## 6. Time and video handling

Timestamps are authoritative for elapsed time. Do not use `frame_number / FPS` as the sole timestamp source.

Phase 01 must preserve media timestamps where available in the canonical `video_frames(video_id, frame_number, pts_s)` table, detect/flag variable-frame-rate video, and record wall-clock start time where available. Downstream phases must use those timestamps rather than reconstructing time from frame number and nominal FPS. OpenCV frame seeking must not be treated as inherently frame-exact for VFR DVR footage.

Frame skipping is an inference/performance choice and must not redefine elapsed time.

## 7. Detection and vehicle classes

YOLO is detection only. The project class mapping is configurable and must be explicit.

Do not assume COCO provides every required Kerala vehicle class. Auto-rickshaw support must be represented through the configured model/class mapping rather than invented COCO semantics.

Detection records retain source frame/timestamp, class, confidence, and full bounding-box geometry.

If tiled inference is enabled, overlapping tile detections must be merged deterministically.

## 8. Tracking

Tracking is a separate layer after detection.

Phase 03 must feed detections into Ultralytics' ByteTrack implementation directly rather than coupling tracking to `model.track()`, because the pipeline must remain capable of accepting merged/tiled detections.

Tracker parameters that represent time must be configured in seconds and converted to frame-based internals using the actual processing cadence. A frame-based `track_buffer` must not accidentally scale with frame skipping.

ID switches and incomplete tracks are data-quality events, not reasons to fabricate continuity.

## 9. Ground point and geometry

For road-surface projection, use the configurable bottom-centre of each vehicle bounding box as the default ground point.

Do not use the bounding-box centre as the physical road reference point by default. The box centre is above the road surface, especially for buses and trucks.

Calibration is a planar-road assumption and must document that assumption.

## 10. Calibration

Use a homography/perspective transformation only when the study geometry supports the flat-road assumption.

Use at least six corresponding reference points. Hold out one or two points for validation rather than fitting and testing on the same points.

Report mean and maximum held-out reprojection error in metres and reject calibration above a configured threshold.

Check/flag wide-angle lens distortion before treating the homography as valid.

Physical units are unavailable until calibration is accepted.

## 11. Approaches, zones, and movements

Phase 05 owns entry and exit zones as well as counting-line configuration.

A single line crossing cannot by itself determine left/through/right movement. Phase 06 derives movement from the configured entry approach and exit approach/zone trajectory.

Movement may be `left`, `through`, `right`, `u_turn`, or `unknown`.

## 12. Counting

Phase 06 records raw crossing events exactly once per configured line/track/direction according to configuration.

Traffic volume must retain raw events and support:
- 15-minute bins
- observed-period counts
- vehicles/hour extrapolation

Acceptance must use a predefined manually counted ground-truth set from 2–3 short clips representing different conditions. The tolerance must be configured before acceptance review.

## 13. Speed

Speed is derived only from accepted calibrated world coordinates and authoritative timestamps.

Invalid or insufficient trajectories produce explicit unavailable/invalid statuses, never fabricated values.

## 14. Queue and stopped vehicles

Queue classification is configurable using queue zones, the calibrated bottom-centre trajectory, speed threshold, and minimum duration.

The canonical field is `queue_length_m`.

## 15. Manual review

Review preserves the original prediction and stores corrections separately.

A correction may change both class and bounding-box geometry. Review data must retain source video/run/frame/timestamp references.

Other emissions-specific features are explicitly out of scope.

## 16. Active learning

Corrected samples become training candidates only after review/approval.

Train/validation/test splits are performed by source-video or source-segment groups, never by adjacent frames. The initial labelled set must have a documented origin.

No corrected sample is automatically placed in the test set.

## 17. Model improvement

Models are versioned. Candidate models are evaluated before selection. The production/active model is never silently replaced by training code.

Evaluation includes detection metrics where labels exist and traffic/tracking metrics relevant to this project.

## 18. Validation

Validation data must be explicitly identified and traceable.

Relevant measures include:
- detection precision/recall/mAP where applicable
- counting absolute and percentage error
- speed MAE/RMSE where reference speeds exist
- queue-length difference where manual reference exists
- ID switches and track continuity

Do not use vague completion language such as "under normal conditions" as the only acceptance criterion.

## 19. Error handling and scientific integrity

Do not fabricate measurements, silently discard failed records, or silently overwrite previous runs.

Invalid calibration, missing timestamps, tracking loss, insufficient trajectory length, and other limitations must be represented explicitly and logged.

## 20. Implementation contract

Every phase prompt must:
1. Name the master sections it implements.
2. State dependencies.
3. State explicit exclusions.
4. Reference the canonical schema/data dictionary.
5. Define required configuration and provenance.
6. Define measurable completion criteria.
7. Require a `HANDOFF.md` describing interfaces, schema/config changes, tests/raw output, limitations, and next-phase dependencies.
8. State the independent-review instruction exactly:

> Do not perform the final checks or acceptance review in this task. Prompt checking, implementation review, testing review, and completion verification will be performed separately by Pro subagents that are different from the normal implementation model.

The implementation model runs tests relevant to its own work and reports the raw output. It does not declare acceptance.

## 21. Out of scope

Do not implement:
- final congestion-index methodology
- emission-factor or pollutant calculations
- CO2/CO/NOx/PM modelling
- MCE
- intersection redesign generation
- SUMO simulation

## 22. Phase gates

Only the following contracts are mandatory before Phase 01: run lineage and configuration snapshot, authoritative per-frame timestamps, database-enforced statuses/foreign keys, streaming video handling, and ownership of the minimal API/frontend skeleton. Later prompt changes are phase-gated and should be made immediately before the phase that consumes them rather than pulled into Phase 01 prematurely.

The following gates are mandatory before their consuming phases:
- Phase 02: rectangular crop configuration plus CPU fallback and GPU OOM behavior.
- Phases 03/12: tracking quality proxies in Phase 03 and MOT-format ID-switch evaluation in Phase 12.
- Phase 06: `video_segments`, ground-truth tables, and frozen acceptance criteria.
- Phase 10: reviewer, review time, and snippet-path fields for manual review.
- Phase 13: frozen export contract, with required fields defined before Phase 08 so upstream data capture can support it.
- Phase 09: explicit signal-phase scope decision before implementation.

Ground-truth preparation is a parallel research activity, not a prompt dependency: begin recording and hand-counting 2–3 short clips while Phase 01 is implemented.

## 23. Development order

01 Video input/playback and foundational scaffolding
02 YOLO detection
03 ByteTrack
04 Trajectories/visualization
05 ROI, entry/exit zones, counting-line configuration
06 Counting, movement derivation, ground-truth counting set
07 Calibration
08 Speed
09 Queue/stopped vehicles
10 Manual review
11 Active-learning dataset
12 Model training/evaluation
13 Export/dashboard

Keep the application runnable after each phase.