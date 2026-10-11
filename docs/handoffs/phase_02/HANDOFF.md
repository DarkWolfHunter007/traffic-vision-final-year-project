# Phase 02 Handoff — YOLO Detection and Preprocessing

## Delivered interfaces

- `backend.detection.UltralyticsDetector`: a detection-only Ultralytics adapter. It never calls `model.track()`.
- `backend.services.detection.run_detection(parent_run_id, config, repository_root, detector)`: creates an immutable child run and persists canonical detection rows.
- `traffic-vision detect PARENT_RUN_ID --config CONFIG`: runs a configured model when the user supplies local weights and an explicit mapping.

## Configuration keys

`detection.model.version`, `detection.model.path`, `detection.model.device`, `detection.confidence_threshold`, `detection.iou_threshold`, `detection.image_size`, `detection.frame_stride`, `detection.roi_crop`, `detection.tiling`, and `detection.class_mapping` are captured in each run's full configuration snapshot and hash.

The class mapping is mandatory for every detected model label. There is no automatic auto-rickshaw mapping and no fallback semantic guess.

## Data contract

Detection runs reference a Phase 01 parent run, copy the parent source-video provenance, register the supplied model file's SHA-256, and write `detections` with run ID, source frame/timestamp, full-frame geometry, confidence, explicit class, and bottom-centre ground point. No tracker IDs or track rows are created.

## Tests and software fixtures

```text
uv run pytest
16 passed
```

Tests cover explicit class mapping, empty-safe preprocessing primitives, ROI validation, deterministic tile coverage, class-aware duplicate merging, and an end-to-end generated software video fixture. The fixture uses a fake detector and fake model file; it is not Pattom footage and is not detector-accuracy evidence.

## Limitations and next phase

- No actual YOLO weights or Pattom footage are included or downloaded.
- CPU PyTorch is installed; no GPU performance claim is made.
- Actual model selection, fine-tuning, auto-rickshaw performance, and count accuracy remain unvalidated.
- Phase 03 may consume canonical `detections` to add tracking. It must keep tracking separate and preserve run provenance.
