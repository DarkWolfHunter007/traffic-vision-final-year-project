# Traffic Vision

YOLO-based vehicle detection, tracking, and traffic-data extraction from recorded CCTV traffic footage.

Traffic Vision is an offline computer-vision subsystem for a final-year Civil Engineering study of Pattom Intersection, Thiruvananthapuram, Kerala. It produces traceable vehicle-level data for later traffic/emission analysis.

## Scope

Included:
- video ingestion and preprocessing
- YOLO detection and configurable vehicle-class mapping
- ByteTrack tracking
- trajectories and visualization
- ROI, entry/exit zones, and counting lines
- movement-aware traffic counting
- camera calibration
- speed estimation
- stopped/queue detection
- manual review and bounding-box correction
- active-learning dataset preparation
- model evaluation
- CSV/JSON/SQLite export and research dashboard

Excluded:
- final congestion-index methodology
- emission/pollutant calculations
- MCE
- intersection redesign generation
- SUMO simulation

## Prompt architecture

All implementation prompts live in `prompts/`.

```text
prompts/
├── master_prompt.md
├── review_checklist.md
├── phase_01_video_input_and_playback.md
├── phase_02_yolo_detection.md
├── phase_03_bytetrack_integration.md
├── phase_04_trajectories_and_visualization.md
├── phase_05_roi_and_counting_lines.md
├── phase_06_vehicle_counting.md
├── phase_07_camera_calibration.md
├── phase_08_speed_estimation.md
├── phase_09_queue_detection.md
├── phase_10_manual_review.md
├── phase_11_active_learning_dataset.md
├── phase_12_model_evaluation.md
└── phase_13_export_and_dashboard.md
```

The master prompt is reference-only. Its first implementation rule is:

> Implement nothing except the phase you are given.

Phase prompts are sequential, independently executable, and explicitly bounded. Each phase must document what it changed and create a `HANDOFF.md` for the next phase.

Independent review is performed separately by Pro subagents. The implementation model runs its own tests and reports raw output but does not declare acceptance.

## Canonical data contract

The source of truth for field names and provenance is:

- `backend/database/schema.sql`
- `docs/data_dictionary.md`

Key rules:
- every derived/result table carries `run_id`
- every source video has a SHA-256
- every processing run records model version and configuration hash
- `timestamp_s` is authoritative for elapsed time
- `frame_number / FPS` is not an authoritative timestamp for VFR footage
- `queue_length_m` is the canonical queue-length field
- `corrected_class` and `corrected_bbox_json` are the canonical correction fields
- bottom-centre is the default physical ground point
- calibration requires held-out validation points
- dataset splits are by source video/segment, never adjacent frames

## Phase ownership

| Phase | Responsibility |
|---|---|
| 01 | Video input, timestamps, preprocessing/scaffolding, config, DB bootstrap, logging |
| 02 | YOLO detection, tiling/merge, class mapping |
| 03 | Direct ByteTrack integration and tracking quality |
| 04 | Trajectories, ground points, visualization |
| 05 | ROI, entry/exit zones, counting-line configuration |
| 06 | Counting, movement derivation, 15-minute bins, ground-truth counting set |
| 07 | Homography calibration and diagnostics |
| 08 | Speed estimation |
| 09 | Stopped/queue detection |
| 10 | Manual review and bounding-box correction |
| 11 | Training dataset/versioned split management |
| 12 | Model training and evaluation |
| 13 | Export and dashboard |

## Development roadmap

```text
[ ] 01 Video input + foundational scaffolding
[ ] 02 YOLO detection
[ ] 03 ByteTrack
[ ] 04 Trajectories + visualization
[ ] 05 ROI + entry/exit zones + counting lines
[ ] 06 Counting + movement + ground truth
[ ] 07 Calibration
[ ] 08 Speed
[ ] 09 Queue/stopped vehicles
[ ] 10 Manual review
[ ] 11 Active-learning dataset
[ ] 12 Model evaluation
[ ] 13 Export + dashboard
```

## Repository structure

```text
traffic-vision/
├── backend/
│   ├── api/
│   ├── services/
│   ├── models/
│   └── database/
│       └── schema.sql
├── frontend/
├── cv/
├── data/
├── models/
├── tests/
├── configs/
├── scripts/
├── docs/
│   └── data_dictionary.md
├── prompts/
├── requirements.txt
└── README.md
```

The exact implementation structure may evolve, but the canonical schema/data dictionary and prompt contracts must remain stable unless deliberately versioned.