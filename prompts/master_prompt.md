# Build a YOLO-Based Traffic Data Collection & Vehicle Tracking Application

## 1. Project Context

I am working on a final-year Civil Engineering project based on traffic and emission analysis at **Pattom Intersection, Thiruvananthapuram, Kerala, India**.

The overall research pipeline is:

Traffic CCTV Video
→ YOLO Vehicle Detection
→ Vehicle Tracking
→ Traffic Data Extraction
→ Congestion Analysis
→ Emission Estimation
→ Intersection Redesign
→ MCE
→ SUMO Validation

Your task is to build ONLY the **computer-vision/data-collection subsystem**.

The application must take recorded CCTV traffic footage as input and produce a structured dataset containing vehicle detections, classifications, trajectories, counts, speeds, queue-related information, and timestamps.

This is an **offline video-analysis application**, NOT a real-time surveillance system. Accuracy and traceability are more important than achieving real-time FPS.

---

# 2. Primary Objectives

Build an application that can:

1. Upload/select a traffic video.
2. Display the video.
3. Run YOLO vehicle detection.
4. Track detected vehicles using ByteTrack.
5. Assign persistent IDs to vehicles.
6. Display bounding boxes, class names, confidence scores and IDs.
7. Allow the user to define Regions of Interest (ROI).
8. Allow the user to define virtual counting lines.
9. Count vehicles crossing each line without double-counting.
10. Allow real-world calibration using manually measured reference points.
11. Transform image coordinates into approximate real-world coordinates.
12. Estimate vehicle speed from trajectory data.
13. Identify stopped/slow vehicles.
14. Estimate queue length based on configurable rules.
15. Store all vehicle-level observations in structured CSV/JSON/SQLite format.
16. Flag uncertain detections for manual review.
17. Generate short video snippets around uncertain events.
18. Allow manual correction of flagged detections.
19. Store corrections separately as training data.
20. Provide a mechanism for periodically fine-tuning the YOLO model using corrected samples.
21. Provide useful visualizations and summary statistics.
22. Export the complete processed dataset.

Do NOT implement the congestion index, emission calculation, MCE or SUMO in this version.

---

# 3. Recommended Technology Stack

Use a Python-based architecture.

Preferred stack:

* Python 3.12
* Ultralytics YOLO
* OpenCV
* ByteTrack
* NumPy
* Pandas
* PyTorch
* SQLite for metadata/results
* FastAPI for backend APIs
* React + TypeScript for frontend
* Tailwind CSS for UI
* FFmpeg where required for video processing

Keep the architecture modular so components can later be replaced.

The YOLO model should NOT be hardcoded to one model version. Make the model path configurable.

Example:

`models/best.pt`

The application should also support a pretrained Ultralytics model initially for testing.

---

# 4. High-Level Architecture

Implement:

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
                │                  ▼
                │             Corrections
                │                  │
                └────────┬─────────┘
                         ▼
                 Training Dataset
                         │
                         ▼
                  Model Fine-tuning
```

---

# 5. Video Input Module

Create a video upload/import interface.

The user should be able to select:

* MP4
* AVI
* MOV
* MKV where supported

After loading, display:

* Video resolution
* FPS
* Duration
* Total frames
* Frame count
* Current frame number
* Current timestamp

The application should NOT load the entire video into memory.

Process frames sequentially or in controlled batches.

---

# 6. Video Preprocessing

Provide configurable options:

* Frame skip
* Inference resolution
* ROI cropping
* Optional image enhancement
* Optional frame resizing
* Optional image tiling/slicing

Example:

```text
Original frame
      ↓
ROI
      ↓
Optional slicing
      ↓
YOLO
```

Tiling should support overlap to prevent vehicles near tile boundaries from being missed.

Implement non-maximum suppression/duplicate merging appropriately when tiled inference generates duplicate detections.

Do not force tiling if normal inference is sufficient.

---

# 7. YOLO Detection Module

Create a dedicated detection service.

For every frame:

```python
detections = model(frame)
```

Each detection must contain:

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

Support configurable confidence threshold.

Example:

```text
confidence_threshold = 0.40
```

Make this configurable from the UI.

Allow the user to select which vehicle classes are relevant.

Possible initial classes:

* car
* motorcycle
* bus
* truck
* bicycle
* auto-rickshaw

Do NOT assume these classes are definitely correct for the final project. Make the class configuration editable.

---

# 8. Vehicle Tracking

Integrate ByteTrack after YOLO detection.

Pipeline:

```text
Frame
 ↓
YOLO
 ↓
Detections
 ↓
ByteTrack
 ↓
Tracked vehicles
```

Every vehicle should receive a persistent tracking ID.

Example:

```text
Frame 100 → Car → ID 17
Frame 101 → Car → ID 17
Frame 102 → Car → ID 17
```

Store trajectory history:

```text
track_id
frame_number
timestamp
class
confidence
center_x
center_y
bbox
```

Handle:

* Temporary missed detections
* Occlusion
* Track creation
* Track termination
* ID switches

Expose tracking configuration parameters where practical.

---

# 9. Visualization

The processed video should support overlays.

Example:

```text
┌─────────────────────────────────────┐
│                                     │
│       🚗 ID: 17                     │
│       Car  0.91                     │
│                                     │
│          🏍 ID: 21                  │
│          Motorcycle 0.87            │
│                                     │
│────── COUNTING LINE ────────────────│
│                                     │
└─────────────────────────────────────┘
```

Overlay:

* Bounding box
* Vehicle class
* Confidence
* Track ID
* Trajectory
* ROI
* Counting lines
* Calibration points
* Queue region

Allow each overlay to be toggled on/off.

---

# 10. ROI Configuration

Create an interface allowing the user to draw polygonal ROIs.

Example:

```text
             Intersection
                  ↓

       ┌────────────────────┐
       │                    │
       │       ROI          │
       │                    │
       └────────────────────┘
```

Only detections inside the configured ROI should optionally be processed.

Allow multiple ROIs.

Each ROI should have:

```text
roi_id
name
polygon_points
approach
movement
```

Store configuration in JSON or SQLite.

---

# 11. Virtual Counting Lines

Allow the user to draw a line on the video.

Example:

```text
         Traffic
           ↓
      🚗  🚗  🚗

========================
       COUNT LINE

           ↓
      Intersection
```

When a tracked vehicle crosses the line:

```text
track_id = 17
class = car
timestamp = 00:03:24
direction = incoming
```

Record exactly one crossing event for that vehicle per configured counting line unless the user explicitly configures bidirectional counting.

Prevent double-counting.

Store:

```text
line_id
track_id
vehicle_class
timestamp
direction
frame_number
```

Calculate:

```text
vehicles per observation period
vehicles/hour
```

---

# 12. Approach and Movement Classification

Allow the user to assign counting lines and ROIs to approaches.

Example:

```text
North
South
East
West
```

Allow configurable movement:

```text
Left
Through
Right
U-turn
Unknown
```

Do not hardcode Pattom's exact movements.

The researcher should configure them through the UI.

---

# 13. Camera Calibration

Implement a calibration module.

The user should be able to select known points in the image.

Example:

```text
Image:

A ●────────────────● B
       known distance
          10 m
```

The user enters the real-world coordinates/distance associated with the points.

Prefer a homography/perspective transformation using multiple corresponding points.

Allow at least four reference points for planar transformation.

Store:

```text
image_x
image_y
world_x
world_y
```

Calculate transformation matrix.

The transformed coordinate should be available for every tracked vehicle.

Example:

```text
pixel:
(842, 512)

world:
(14.2m, 7.8m)
```

Do not assume that a single pixel-to-meter ratio is universally valid across the image.

---

# 14. Speed Estimation

Using:

```text
track_id
timestamp
world_x
world_y
```

estimate vehicle speed.

Basic:

```text
distance = sqrt(
    (x2-x1)^2 +
    (y2-y1)^2
)

speed = distance / time
```

Convert to km/h:

```text
km/h = m/s × 3.6
```

Apply smoothing to reduce frame-level noise.

Provide configurable smoothing/window parameters.

Store:

```text
track_id
timestamp
speed_mps
speed_kmh
```

Avoid calculating speed when insufficient trajectory information exists.

Flag unreliable estimates instead of generating fake values.

---

# 15. Stopped/Slow Vehicle Detection

Create configurable thresholds.

Example:

```text
STOP_SPEED_THRESHOLD = 2 km/h
```

If the vehicle remains below the threshold for a configurable duration:

```text
Vehicle → stopped
```

Store:

```text
track_id
start_time
end_time
duration
location
```

Do NOT hardcode the final threshold without allowing the researcher to change it.

---

# 16. Queue Detection

Create a configurable queue region near each stop line.

A vehicle can be considered queued when:

```text
vehicle is inside queue ROI
AND
vehicle speed < configurable threshold
AND
vehicle satisfies minimum stopping duration
```

Calculate queue length using the calibrated world coordinates.

Example:

```text
STOP LINE
│
│ 🚗
│ 🚗
│ 🚗
│ 🚗 ← furthest queued vehicle
│
```

Store:

```text
approach
timestamp
queue_length_m
number_of_queued_vehicles
```

Allow the methodology thresholds to be changed through configuration.

---

# 17. Signal Phase Annotation

Because the study concerns an intersection, provide an optional mechanism for defining signal phases.

Allow the researcher to enter:

```text
RED
GREEN
AMBER
```

with timestamps or cycle definitions.

This information can later be used for delay/queue analysis.

Do not attempt to automatically infer signal phases in the first version.

---

# 18. Manual Review / Human-in-the-Loop

This is an important feature.

The system should detect uncertain cases.

Examples:

```text
confidence < threshold
```

or:

* vehicle classification uncertainty
* tracking failure
* severe occlusion
* unreadable number plate
* suspicious tracking event

Flag these events.

For every flagged event, automatically generate a short video snippet:

```text
5 seconds before event
+
event
+
5 seconds after event
```

The exact duration should be configurable.

The review UI should show:

```text
Video snippet

Prediction:
Class = car
Confidence = 0.42

[ Car ]
[ Motorcycle ]
[ Bus ]
[ Truck ]
[ Other ]
```

The researcher can correct the prediction.

Store:

```text
original_prediction
corrected_label
frame/video reference
timestamp
track_id
```

---

# 19. Active Learning Dataset

Corrected samples should be stored in a dedicated dataset:

```text
dataset/
    images/
    labels/
    metadata/
```

Maintain a distinction between:

```text
original training data
validation data
new corrected data
test data
```

Never automatically put every corrected sample into the test set.

Provide a dataset-management module.

---

# 20. Model Improvement Loop

Implement a controlled workflow:

```text
YOLO inference
      ↓
Uncertain samples
      ↓
Human correction
      ↓
Corrected dataset
      ↓
Dataset review
      ↓
Fine-tuning
      ↓
New model
      ↓
Evaluation
```

Do NOT automatically replace the production model after training.

Instead:

```text
Model v1
Model v2
Model v3
```

Allow the researcher to compare:

* Precision
* Recall
* mAP
* Confusion matrix
* Detection count
* Tracking quality

Then manually select which model becomes active.

This is an **active-learning/human-in-the-loop system**, not reinforcement learning.

---

# 21. Data Storage

Use SQLite for application metadata and structured results.

Suggested tables:

### videos

```text
id
filename
path
fps
width
height
duration
created_at
```

### detections

```text
id
video_id
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
```

### tracks

```text
track_id
video_id
frame_number
timestamp
class_name
confidence
image_x
image_y
world_x
world_y
speed_kmh
```

### crossing_events

```text
id
video_id
line_id
track_id
timestamp
direction
vehicle_class
```

### queue_events

```text
id
video_id
approach
timestamp
queue_length
queued_vehicle_count
```

### manual_reviews

```text
id
video_id
track_id
timestamp
original_class
corrected_class
reason
review_status
```

---

# 22. Export

Allow export to:

### CSV

```text
vehicle_id
timestamp
vehicle_class
approach
movement
x
y
world_x
world_y
speed_kmh
queue_status
```

### JSON

For complete trajectory information.

### SQLite

For the complete project database.

Also export summary:

```text
Total vehicles
Vehicles by class
Vehicles/hour
Average speed
Maximum speed
Average stopped time
Maximum queue length
Average queue length
```

---

# 23. Dashboard

Create a simple research-oriented dashboard.

Display:

```text
VIDEO
Duration: 30 min
FPS: 25
Resolution: 1920×1080

VEHICLES
Total detected: 2,481
Cars: 1,340
Motorcycles: 820
Buses: 121
Trucks: 200

TRAFFIC
Volume: XXXX veh/h
Average speed: XX km/h
Maximum queue: XX m
Average queue: XX m

TRACKING
Active tracks: XX
ID switches: XX
Low-confidence events: XX
```

The dashboard should not claim that these numbers are scientifically valid until processing/validation has completed.

---

# 24. Error Handling

The application must gracefully handle:

* Corrupted video
* Unsupported video format
* Missing YOLO model
* GPU unavailable
* Insufficient GPU memory
* Empty detections
* Tracking failures
* Invalid calibration
* Missing reference points
* Invalid ROI
* Invalid counting line
* OCR failure
* Missing frames

Do not silently continue with invalid data.

Log errors clearly.

---

# 25. Performance Architecture

Because this is offline processing, prioritize accuracy.

Use:

```text
Video Reader
      ↓
Frame Queue
      ↓
Preprocessing Worker
      ↓
YOLO Inference
      ↓
Tracking
      ↓
Analytics
      ↓
Database Writer
```

Use multiprocessing/threading only where it actually improves throughput.

Do not create unnecessary complexity.

If GPU is available:

```text
PyTorch CUDA → YOLO inference
```

If GPU is unavailable:

```text
CPU inference
```

The application must still function.

---

# 26. Configuration

Create a central configuration file:

```yaml
model:
  path: models/best.pt
  confidence_threshold: 0.40
  iou_threshold: 0.50
  imgsz: 1280

tracking:
  tracker: bytetrack
  track_buffer: 30

speed:
  smoothing_window: 5
  minimum_distance_m: 2

queue:
  speed_threshold_kmh: 2
  minimum_stop_duration_s: 3

review:
  confidence_threshold: 0.40
  snippet_before_s: 5
  snippet_after_s: 5
```

Make important parameters editable through the UI.

---

# 27. Important Scientific Requirements

The application must NOT fabricate measurements.

If calibration is missing:

```text
Do not report metres or km/h.
```

If speed cannot be reliably estimated:

```text
Return unavailable/invalid.
```

If vehicle fuel type cannot be identified:

```text
Mark as unknown/manual review.
```

If tracking is lost:

```text
Mark trajectory as incomplete.
```

Every derived measurement should retain enough metadata to trace it back to the original video.

This is important because the application will ultimately be used for academic research.

---

# 28. Validation Module

Provide a way to manually enter ground-truth observations for selected video segments.

Example:

```text
Manual vehicles = 103
System vehicles = 99
```

Calculate appropriate comparison metrics.

For detection:

* Precision
* Recall
* mAP

For counting:

* Absolute error
* Percentage error

For speed:

* MAE/RMSE against manually measured/reference speeds where available

For queue:

* Difference between manually measured and system-estimated queue length

For tracking:

* ID switches
* Track continuity where appropriate

Display these results in the dashboard.

---

# 29. Development Strategy

Do NOT attempt to build everything simultaneously.

Build in this order:

### Phase 1

Video upload + video player

### Phase 2

YOLO detection

### Phase 3

ByteTrack

### Phase 4

Bounding boxes + IDs + trajectories

### Phase 5

ROI and virtual counting lines

### Phase 6

Vehicle counting

### Phase 7

Camera calibration

### Phase 8

Speed estimation

### Phase 9

Queue/stopped vehicle detection

### Phase 10

Manual review

### Phase 11

Active-learning dataset

### Phase 12

Model fine-tuning/evaluation

### Phase 13

Export + dashboard

Do not move to the next phase until the previous phase produces verifiable results.

---

# 30. Expected Final Output

The final application should allow me to take:

```text
Pattom_CCTV_01.mp4
```

and produce:

```text
Processed video
        +
Vehicle detections
        +
Persistent tracking IDs
        +
Vehicle trajectories
        +
Vehicle counts
        +
Speed estimates
        +
Queue estimates
        +
Stopped-time estimates
        +
Manual-review samples
        +
Corrected training data
        +
Validation metrics
        +
CSV/JSON/SQLite dataset
```

The resulting dataset will later be consumed by a separate traffic/emission-analysis module.

---

# 31. Critical Design Principle

Keep these layers strictly separated:

```text
YOLO
=
Detection

ByteTrack
=
Tracking

Calibration
=
Pixel → real-world coordinates

Trajectory engine
=
Movement information

Traffic analytics
=
Volume / speed / queue / delay

Emission model
=
Traffic activity → emissions

SUMO
=
Traffic simulation and validation
```

Do not mix emission calculations into the YOLO code.

The computer-vision application should produce clean, traceable **vehicle-level traffic data** that another module can consume.

---

# 32. Deliverables

Generate:

1. Complete source code
2. Frontend
3. Backend
4. Database schema
5. Configuration system
6. YOLO inference module
7. ByteTrack integration
8. Calibration module
9. Counting-line module
10. Speed module
11. Queue module
12. Manual-review interface
13. Active-learning dataset pipeline
14. Model evaluation module
15. CSV/JSON export
16. SQLite database
17. README
18. Installation instructions
19. Example configuration
20. Test dataset/examples
21. Unit tests for critical components

Before writing large amounts of code, create the project structure and explain the architecture briefly. Then implement each phase incrementally, keeping the application runnable after every phase.


---

## Prompt Governance

Implementation prompts are organized under `prompts/`. The master prompt defines the complete system; phase prompts define sequential, bounded implementation tasks. Each phase must preserve the separation between computer vision, traffic analytics, emission modelling, and SUMO.

Independent prompt checking, implementation review, testing review, and completion verification are performed separately by Pro subagents. The implementation model must not claim independent acceptance.
