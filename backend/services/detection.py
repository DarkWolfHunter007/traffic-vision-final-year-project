"""Phase 02 detection-run orchestration; tracking is deliberately excluded."""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.config import canonical_json, config_hash
from backend.database.connection import database_connection, schema_version
from backend.database.repository import insert_detections, insert_model_version, insert_run, update_run_status
from backend.detection import Detection, Detector, RawDetection, crop_image, generate_tiles, map_detection, merge_tile_detections, validate_roi_crop
from backend.media import iter_decoded_images, sha256_file
from backend.services.ingestion import _utc_now, current_code_version


def detect_image(image: Any, config: dict[str, Any], detector: Detector) -> list[Detection]:
    """Run configured ROI/tile detection and return full-frame canonical geometry."""
    settings = config["detection"]
    roi = validate_roi_crop(settings["roi_crop"], image.shape[1], image.shape[0])
    cropped, roi_x, roi_y = crop_image(image, roi)
    tiling = settings["tiling"]
    tiles = generate_tiles(cropped.shape[1], cropped.shape[0], tiling["width"], tiling["height"], tiling["overlap"]) if tiling["enabled"] else [None]
    raw_detections: list[RawDetection] = []
    for tile in tiles:
        if tile is None:
            tile_image, x_offset, y_offset = cropped, roi_x, roi_y
        else:
            tile_image = cropped[tile.y : tile.y + tile.height, tile.x : tile.x + tile.width]
            x_offset, y_offset = roi_x + tile.x, roi_y + tile.y
        raw_detections.extend(
            detection.translated(x_offset, y_offset)
            for detection in detector.predict(tile_image, confidence=settings["confidence_threshold"], iou=settings["iou_threshold"], image_size=settings["image_size"])
        )
    return [map_detection(raw, settings["class_mapping"]) for raw in merge_tile_detections(raw_detections, settings["iou_threshold"])]


def run_detection(parent_run_id: str, config: dict[str, Any], repository_root: Path, detector: Detector) -> str:
    """Create one immutable detection run derived from an ingested parent run."""
    database_path = Path(config["paths"]["database_path"])
    if not database_path.is_absolute():
        database_path = repository_root / database_path
    model = config["detection"]["model"]
    if not model["version"] or not model["path"]:
        raise ValueError("detection.model.version and an existing detection.model.path are required")
    model_path = Path(model["path"])
    if not model_path.is_absolute():
        model_path = repository_root / model_path
    if not model_path.is_file():
        raise ValueError("detection.model.path must reference an existing model weights file")
    run_id = str(uuid4())
    with database_connection(database_path) as connection:
        parent = connection.execute("SELECT video_id, source_video_sha256 FROM processing_runs WHERE run_id = ?", (parent_run_id,)).fetchone()
        if parent is None:
            raise ValueError(f"Parent processing run does not exist: {parent_run_id}")
        video = connection.execute("SELECT path FROM videos WHERE video_id = ?", (parent["video_id"],)).fetchone()
        if video is None:
            raise ValueError("Parent run references a missing video")
        insert_model_version(connection, {"model_version": model["version"], "model_path": str(model_path.resolve()), "sha256": sha256_file(model_path), "dataset_version": None, "created_at": _utc_now(), "metrics_json": json.dumps({})})
        insert_run(connection, {"run_id": run_id, "parent_run_id": parent_run_id, "video_id": parent["video_id"], "model_version": model["version"], "config_hash": config_hash(config), "config_json": canonical_json(config), "schema_version": schema_version(), "code_version": current_code_version(repository_root), "source_video_sha256": parent["source_video_sha256"], "started_at": _utc_now(), "status": "running", "notes": "Phase 02 detection run"})
    try:
        with database_connection(database_path) as connection:
            for frame_number, timestamp_s, image in iter_decoded_images(Path(video["path"])):
                if frame_number % config["detection"]["frame_stride"]:
                    continue
                detections = detect_image(image, config, detector)
                insert_detections(connection, ({"detection_id": str(uuid4()), "run_id": run_id, "video_id": parent["video_id"], "frame_number": frame_number, "timestamp_s": timestamp_s, "class_id": detection.class_id, "class_name": detection.class_name, "confidence": detection.confidence, "x1": detection.x1, "y1": detection.y1, "x2": detection.x2, "y2": detection.y2, "ground_x": detection.ground_x, "ground_y": detection.ground_y, "width_px": detection.width_px, "height_px": detection.height_px} for detection in detections))
            update_run_status(connection, run_id, "completed", completed_at=_utc_now())
    except Exception as error:
        with database_connection(database_path) as connection:
            update_run_status(connection, run_id, "failed", completed_at=_utc_now(), notes=str(error))
        raise
    return run_id
