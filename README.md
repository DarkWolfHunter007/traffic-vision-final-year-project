# Traffic Vision

YOLO-based vehicle detection, tracking, and traffic data extraction from CCTV traffic footage.

Traffic Vision is an offline computer-vision system developed as part of a final-year Civil Engineering project for analysing traffic conditions at intersections.

The system converts recorded CCTV footage into structured, vehicle-level traffic data that can later be used for congestion analysis, emission estimation, and intersection redesign.

## Project Context

The overall research workflow is:

```text
CCTV Traffic Video
        ↓
YOLO Vehicle Detection
        ↓
Vehicle Classification
        ↓
ByteTrack Tracking
        ↓
Vehicle Trajectories
        ↓
Traffic Data Extraction
        ↓
Congestion Analysis
        ↓
Emission Estimation
        ↓
Intersection Redesign
        ↓
MCE
        ↓
SUMO Validation
```

This repository focuses specifically on the **computer-vision and traffic-data extraction stage**.

It does not directly calculate the final congestion index, emissions, MCE results, or SUMO simulations.

## What the System Does

Traffic Vision is designed to extract:

* Vehicle detections
* Vehicle classifications
* Persistent vehicle IDs
* Vehicle trajectories
* Traffic volume
* Vehicle speed
* Stopped time
* Queue information
* Counting-line crossings
* Approach/movement information
* Calibrated real-world coordinates
* Manual-review samples
* Corrected training samples
* Detection and tracking validation metrics

The resulting data can be exported for use by later traffic and emission-analysis modules.

## Core Architecture

```text
                    CCTV VIDEO
                         │
                         ▼
                Video Ingestion
                         │
                         ▼
              Video Preprocessing
                         │
                         ▼
                 YOLO Detection
                         │
                         ▼
                   ByteTrack
                         │
                         ▼
               Vehicle Trajectories
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
    Counting Lines     Speed          Queue
          │           Estimation     Detection
          └──────────────┼──────────────┘
                         ▼
                 Traffic Dataset
                         │
                ┌────────┴────────┐
                ▼                 ▼
          Confidence         Manual Review
           Analysis                │
                                   ▼
                              Corrections
                                   │
                                   ▼
                         Active-Learning Dataset
                                   │
                                   ▼
                            Model Fine-tuning
```

## Technology Stack

### Computer Vision

* Python
* Ultralytics YOLO
* PyTorch
* OpenCV
* ByteTrack
* NumPy

### Data Processing

* Pandas
* SQLite
* JSON
* CSV

### Backend

* FastAPI

### Frontend

* React
* TypeScript
* Tailwind CSS

### Video Processing

* FFmpeg

## Main Pipeline

### 1. Video Input

The application accepts recorded CCTV footage.

Supported formats include:

* MP4
* AVI
* MOV
* MKV where supported

Video metadata such as resolution, FPS, duration, and frame count is extracted automatically.

### 2. Preprocessing

The system can optionally apply:

* ROI cropping
* Frame skipping
* Resolution adjustment
* Image enhancement
* Image tiling/slicing

Tiling is intended to improve detection of small vehicles in high-resolution CCTV footage.

### 3. YOLO Detection

YOLO detects vehicles in each processed frame.

Each detection contains:

```text
frame_number
timestamp
class_id
class_name
confidence
x1
y1
x2
y2
center_x
center_y
width
height
```

The YOLO model is configurable and is not tied to a specific model version.

### 4. Vehicle Tracking

ByteTrack associates detections across consecutive frames.

Example:

```text
Frame 100 → Car → ID 17
Frame 101 → Car → ID 17
Frame 102 → Car → ID 17
Frame 103 → Car → ID 17
```

This allows the system to reconstruct individual vehicle trajectories instead of treating every frame-level detection as a separate vehicle.

### 5. Traffic Counting

Virtual counting lines can be configured for individual approaches.

When a tracked vehicle crosses a line, the system records:

```text
track_id
vehicle_class
timestamp
direction
line_id
frame_number
```

This prevents repeated counting of the same vehicle across multiple frames.

Traffic volume can subsequently be calculated from the observed counting events.

### 6. Camera Calibration

Real-world reference points are measured at the physical intersection and identified in the CCTV footage.

The system uses corresponding image/world points to establish a perspective transformation.

```text
Image Coordinates
       ↓
Perspective Transformation
       ↓
Real-World Coordinates
```

This allows measurements such as vehicle position, distance, queue length, and speed to be expressed in physical units.

The system should use multiple reference points rather than assuming a single pixel-to-metre ratio across the entire image.

### 7. Speed Estimation

Vehicle trajectories are transformed into calibrated coordinates.

Speed is estimated from:

```text
Distance travelled
        ÷
Elapsed time
```

and converted to km/h.

Trajectory smoothing can be applied to reduce frame-level measurement noise.

Measurements are marked invalid when insufficient trajectory information exists.

### 8. Queue Detection

A queue region can be configured around the approach and stop line.

A vehicle can be considered queued when it satisfies configurable conditions such as:

* Being inside the queue region
* Having speed below the defined threshold
* Remaining stopped/slow for the required duration

Queue length is calculated using calibrated coordinates.

### 9. Manual Review

The system identifies uncertain cases such as:

* Low-confidence detections
* Classification uncertainty
* Severe occlusion
* Tracking failures
* Unusual vehicle appearances
* Other configurable conditions

A short video snippet surrounding the event can be generated for manual inspection.

The researcher can correct the prediction.

### 10. Active Learning

Corrected samples are stored as training data.

The intended improvement loop is:

```text
YOLO Prediction
      ↓
Uncertain Sample
      ↓
Human Correction
      ↓
Training Dataset
      ↓
Fine-tuning
      ↓
New Model
      ↓
Evaluation
```

This is a **human-in-the-loop active-learning workflow**, not reinforcement learning.

Models are versioned and evaluated before being selected for future inference.

## Data Model

The system maintains structured information for:

### Videos

```text
video_id
filename
path
fps
width
height
duration
created_at
```

### Detections

```text
video_id
frame_number
timestamp
class_id
class_name
confidence
bounding_box
center_coordinates
```

### Tracks

```text
video_id
track_id
frame_number
timestamp
vehicle_class
confidence
image_coordinates
world_coordinates
speed
```

### Crossing Events

```text
video_id
line_id
track_id
timestamp
vehicle_class
direction
```

### Queue Events

```text
video_id
approach
timestamp
queue_length
queued_vehicle_count
```

### Manual Reviews

```text
video_id
track_id
timestamp
original_prediction
corrected_prediction
reason
review_status
```

## Calibration

Calibration is an important requirement for reliable physical measurements.

The workflow is:

```text
Physical Intersection
        ↓
Measure Reference Points
        ↓
Identify Same Points in CCTV
        ↓
Calculate Transformation
        ↓
Transform Vehicle Coordinates
        ↓
Physical Measurements
```

Without valid calibration, the system must not present pixel measurements as metres or calculate physical speed from them.

## Scientific Data Integrity

This project is intended for academic traffic analysis.

The system therefore follows several principles:

* Do not fabricate missing measurements.
* Do not silently discard failed detections.
* Preserve confidence values.
* Preserve tracking information.
* Mark incomplete trajectories.
* Mark unavailable measurements as unavailable.
* Keep manual corrections separate from original predictions.
* Maintain model versions.
* Preserve enough metadata to trace results back to the source video.
* Validate automated results against manually verified samples.

## Validation

The system provides mechanisms for comparing automated results against manually established ground truth.

Possible metrics include:

### Detection

* Precision
* Recall
* mAP

### Traffic Counting

* Absolute error
* Percentage error

### Speed

* MAE
* RMSE

### Queue

* Difference between manually measured and automated queue length

### Tracking

* ID switches
* Track continuity

The exact evaluation methodology will be finalized according to the project's research requirements.

## Project Scope

### Included

* CCTV video processing
* YOLO detection
* Vehicle classification
* ByteTrack tracking
* Trajectory extraction
* ROI configuration
* Counting lines
* Traffic volume extraction
* Camera calibration
* Speed estimation
* Queue detection
* Manual review
* Active-learning dataset generation
* Model evaluation
* Data export

### Not Included

* Final congestion-index methodology
* Emission-factor calculations
* CO₂/CO/NOx/PM modelling
* Multi-criteria evaluation
* Intersection redesign generation
* SUMO simulation

These components will consume the traffic data produced by this repository.

## Development Roadmap

```text
[ ] Phase 1  — Video input and playback
[ ] Phase 2  — YOLO detection
[ ] Phase 3  — ByteTrack integration
[ ] Phase 4  — Trajectories and visualization
[ ] Phase 5  — ROI and counting lines
[ ] Phase 6  — Vehicle counting
[ ] Phase 7  — Camera calibration
[ ] Phase 8  — Speed estimation
[ ] Phase 9  — Queue/stopped vehicle detection
[ ] Phase 10 — Manual review
[ ] Phase 11 — Active-learning dataset
[ ] Phase 12 — Model fine-tuning/evaluation
[ ] Phase 13 — Export and dashboard
```

Each phase should remain independently testable before moving to the next stage.

## Repository Structure

The final structure is expected to follow a modular architecture similar to:

```text
traffic-vision/
│
├── backend/
│   ├── api/
│   ├── services/
│   ├── models/
│   └── database/
│
├── frontend/
│   ├── components/
│   ├── pages/
│   └── services/
│
├── cv/
│   ├── detection/
│   ├── tracking/
│   ├── calibration/
│   ├── counting/
│   ├── speed/
│   └── queue/
│
├── data/
│   ├── raw/
│   ├── processed/
│   ├── annotations/
│   └── datasets/
│
├── models/
│   └── best.pt
│
├── tests/
│
├── configs/
│
├── scripts/
│
├── docs/
│
├── requirements.txt
├── README.md
└── .gitignore
```

The exact structure may evolve during implementation.

## Research Context

The initial study location is **Pattom Intersection, Thiruvananthapuram, Kerala**.

The system is designed to process recorded traffic footage from the study location and generate reliable vehicle-level traffic information for subsequent civil-engineering analysis.

The system should remain location-independent enough to be configured for other intersections without modifying the core computer-vision pipeline.

## Status

🚧 **Research / Development**

This repository is being developed as part of a final-year Civil Engineering project.

The methodology, model configuration, thresholds, vehicle classes, calibration parameters, and evaluation criteria are subject to validation during the research process.
