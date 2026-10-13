"""Configuration loading and deterministic provenance hashing."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

import yaml


DEFAULT_CONFIG: dict[str, Any] = {
    "paths": {
        "raw_root": "data/raw",
        "processed_root": "data/processed",
        "database_path": "data/processed/traffic_vision.sqlite3",
    },
    "input": {"supported_formats": [".avi", ".mkv", ".mov", ".mp4"]},
    "timestamp": {"strategy": "decoder_pts", "wall_clock_start": None},
    "streaming": {"frame_batch_size": 500, "preview_frame_number": 0},
    "resources": {"policy": "cpu", "gpu_oom_behavior": "not_applicable_phase_01"},
    "detection": {
        "model": {"version": None, "path": None, "device": "cpu"},
        "confidence_threshold": 0.25,
        "iou_threshold": 0.45,
        "image_size": 640,
        "frame_stride": 1,
        "roi_crop": None,
        "tiling": {"enabled": False, "width": 640, "height": 640, "overlap": 0.2},
        "class_mapping": {},
    },
    "tracking": {
        "tracker_type": "bytetrack",
        "track_high_thresh": 0.5,
        "track_low_thresh": 0.1,
        "new_track_thresh": 0.6,
        "match_thresh": 0.8,
        "track_buffer_seconds": 1.0,
        "fuse_score": True,
        "chunk_frames": 500,
    },
    "trajectories": {
        "ground_point_method": "bottom_center",
        "max_gap_seconds": 1.0,
        "min_track_length_frames": 3,
        "boundary_margin_px": 20,
    },
    "visualization": {
        "enabled": True,
        "show_boxes": True,
        "show_labels": True,
        "show_confidences": True,
        "show_ids": True,
        "show_trails": True,
        "trail_length": 30,
        "trail_thickness": 2,
        "box_thickness": 2,
        "font_scale": 0.5,
        "output_dir": "data/processed/visualizations",
    },
    "counting": {
        "bin_duration_s": 900.0,
        "min_reentry_gap_s": 2.0,
        "error_tolerance_pct": 10.0,
        "movement_mapping": {
            "north": {"south": "through", "east": "left", "west": "right", "north": "u_turn"},
            "south": {"north": "through", "west": "left", "east": "right", "south": "u_turn"},
            "east": {"west": "through", "north": "right", "south": "left", "east": "u_turn"},
            "west": {"east": "through", "south": "right", "north": "left", "west": "u_turn"},
        },
    },
    "calibration": {
        "method": "planar_homography",
        "min_points": 6,
        "held_out_count": 2,
        "max_reprojection_error_m": 1.0,
        "distortion_check_enabled": False,
        "flat_road_assumption": True,
        "coordinate_unit": "meter",
    },
    "logging": {"level": "INFO"},
}


class ConfigError(ValueError):
    """Raised when a Phase 01 configuration is malformed."""


def _deep_merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def canonical_json(config: Mapping[str, Any]) -> str:
    """Return the stable JSON representation used by processing-run provenance."""
    return json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def config_hash(config: Mapping[str, Any]) -> str:
    return sha256(canonical_json(config).encode("utf-8")).hexdigest()


def _validate(config: Mapping[str, Any]) -> None:
    required_sections = {"paths", "input", "timestamp", "streaming", "resources", "logging"}
    missing = required_sections.difference(config)
    if missing:
        raise ConfigError(f"Missing required configuration sections: {', '.join(sorted(missing))}")
    if not isinstance(config["input"].get("supported_formats"), list):
        raise ConfigError("input.supported_formats must be a list")
    batch_size = config["streaming"].get("frame_batch_size")
    if not isinstance(batch_size, int) or batch_size <= 0:
        raise ConfigError("streaming.frame_batch_size must be a positive integer")
    strategy = config["timestamp"].get("strategy")
    if strategy != "decoder_pts":
        raise ConfigError("Phase 01 requires timestamp.strategy to be 'decoder_pts'")
    detection = config.get("detection")
    if not isinstance(detection, Mapping):
        raise ConfigError("detection must be a mapping")
    if not 0 <= detection.get("confidence_threshold", -1) <= 1:
        raise ConfigError("detection.confidence_threshold must be between zero and one")
    if not 0 < detection.get("iou_threshold", 0) <= 1:
        raise ConfigError("detection.iou_threshold must be greater than zero and at most one")
    if not isinstance(detection.get("frame_stride"), int) or detection["frame_stride"] <= 0:
        raise ConfigError("detection.frame_stride must be a positive integer")
    tiling = detection.get("tiling")
    if not isinstance(tiling, Mapping) or not 0 <= tiling.get("overlap", -1) < 1:
        raise ConfigError("detection.tiling.overlap must be at least zero and below one")
    if not isinstance(detection.get("class_mapping"), Mapping):
        raise ConfigError("detection.class_mapping must be a mapping")
    tracking = config.get("tracking")
    if tracking is not None:
        if not isinstance(tracking, Mapping):
            raise ConfigError("tracking must be a mapping")
        if tracking.get("tracker_type") != "bytetrack":
            raise ConfigError("Phase 03 requires tracking.tracker_type to be 'bytetrack'")
        if not 0 <= tracking.get("track_high_thresh", -1) <= 1:
            raise ConfigError("tracking.track_high_thresh must be between zero and one")
        if not 0 <= tracking.get("track_low_thresh", -1) <= 1:
            raise ConfigError("tracking.track_low_thresh must be between zero and one")
        if not 0 <= tracking.get("new_track_thresh", -1) <= 1:
            raise ConfigError("tracking.new_track_thresh must be between zero and one")
        if not 0 <= tracking.get("match_thresh", -1) <= 1:
            raise ConfigError("tracking.match_thresh must be between zero and one")
        buffer_seconds = tracking.get("track_buffer_seconds")
        if not (isinstance(buffer_seconds, (int, float)) and buffer_seconds > 0):
            raise ConfigError("tracking.track_buffer_seconds must be a positive number")
        chunk_frames = tracking.get("chunk_frames")
        if chunk_frames is not None and not (isinstance(chunk_frames, int) and chunk_frames >= 1):
            raise ConfigError("tracking.chunk_frames must be an integer >= 1")
        batch_size = tracking.get("batch_size")
        if batch_size is not None and not (isinstance(batch_size, int) and batch_size >= 1):
            raise ConfigError("tracking.batch_size must be an integer >= 1")
    trajectories = config.get("trajectories")
    if trajectories is not None:
        if not isinstance(trajectories, Mapping):
            raise ConfigError("trajectories must be a mapping")
        if trajectories.get("ground_point_method") != "bottom_center":
            raise ConfigError("Phase 04 requires trajectories.ground_point_method to be 'bottom_center'")
        max_gap = trajectories.get("max_gap_seconds")
        if not (isinstance(max_gap, (int, float)) and max_gap > 0):
            raise ConfigError("trajectories.max_gap_seconds must be a positive number")
        min_len = trajectories.get("min_track_length_frames")
        if not (isinstance(min_len, int) and min_len >= 1):
            raise ConfigError("trajectories.min_track_length_frames must be a positive integer >= 1")
        margin = trajectories.get("boundary_margin_px")
        if not (isinstance(margin, (int, float)) and margin >= 0):
            raise ConfigError("trajectories.boundary_margin_px must be a non-negative number")
    visualization = config.get("visualization")
    if visualization is not None:
        if not isinstance(visualization, Mapping):
            raise ConfigError("visualization must be a mapping")
        for bool_key in ("enabled", "show_boxes", "show_labels", "show_confidences", "show_ids", "show_trails"):
            if bool_key in visualization and not isinstance(visualization[bool_key], bool):
                raise ConfigError(f"visualization.{bool_key} must be a boolean")
        trail_length = visualization.get("trail_length")
        if trail_length is not None and not (isinstance(trail_length, int) and trail_length >= 0):
            raise ConfigError("visualization.trail_length must be a non-negative integer")
        for int_key in ("trail_thickness", "box_thickness"):
            val = visualization.get(int_key)
            if val is not None and not (isinstance(val, int) and val >= 1):
                raise ConfigError(f"visualization.{int_key} must be an integer >= 1")
        font_scale = visualization.get("font_scale")
        if font_scale is not None and not (isinstance(font_scale, (int, float)) and font_scale > 0):
            raise ConfigError("visualization.font_scale must be a positive number")
    counting = config.get("counting")
    if counting is not None:
        if not isinstance(counting, Mapping):
            raise ConfigError("counting must be a mapping")
        bin_dur = counting.get("bin_duration_s")
        if not (isinstance(bin_dur, (int, float)) and bin_dur > 0):
            raise ConfigError("counting.bin_duration_s must be a positive number")
        reentry_gap = counting.get("min_reentry_gap_s")
        if not (isinstance(reentry_gap, (int, float)) and reentry_gap >= 0):
            raise ConfigError("counting.min_reentry_gap_s must be a non-negative number")
        tol = counting.get("error_tolerance_pct")
        if not (isinstance(tol, (int, float)) and tol > 0):
            raise ConfigError("counting.error_tolerance_pct must be a positive number")
        mapping = counting.get("movement_mapping")
        if mapping is not None and not isinstance(mapping, Mapping):
            raise ConfigError("counting.movement_mapping must be a mapping")
    calibration = config.get("calibration")
    if calibration is not None:
        if not isinstance(calibration, Mapping):
            raise ConfigError("calibration must be a mapping")
        if calibration.get("method") != "planar_homography":
            raise ConfigError("Phase 07 requires calibration.method to be 'planar_homography'")
        min_pts = calibration.get("min_points")
        if not (isinstance(min_pts, int) and min_pts >= 6):
            raise ConfigError("calibration.min_points must be an integer >= 6")
        held_out = calibration.get("held_out_count")
        if not (isinstance(held_out, int) and held_out >= 1):
            raise ConfigError("calibration.held_out_count must be an integer >= 1")
        if min_pts - held_out < 4:
            raise ConfigError("calibration fit points (min_points - held_out_count) must be at least 4")
        max_err = calibration.get("max_reprojection_error_m")
        if not (isinstance(max_err, (int, float)) and max_err > 0):
            raise ConfigError("calibration.max_reprojection_error_m must be a positive number")
        distortion = calibration.get("distortion_check_enabled")
        if distortion is not None and not isinstance(distortion, bool):
            raise ConfigError("calibration.distortion_check_enabled must be a boolean")
        flat_road = calibration.get("flat_road_assumption")
        if flat_road is not True:
            raise ConfigError("Phase 07 requires calibration.flat_road_assumption to be True")
        unit = calibration.get("coordinate_unit")
        if not isinstance(unit, str) or not unit.strip():
            raise ConfigError("calibration.coordinate_unit must be a non-empty string")


def load_config(path: Path | None = None, overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Load a YAML/JSON config over Phase 01 defaults and validate it."""
    loaded: Mapping[str, Any] = {}
    if path is not None:
        if not path.is_file():
            raise ConfigError(f"Configuration file does not exist: {path}")
        try:
            with path.open("r", encoding="utf-8") as config_file:
                loaded = yaml.safe_load(config_file) or {}
        except yaml.YAMLError as error:
            raise ConfigError(f"Invalid configuration file {path}: {error}") from error
        if not isinstance(loaded, Mapping):
            raise ConfigError("Configuration root must be a mapping")

    config = _deep_merge(DEFAULT_CONFIG, loaded)
    if overrides:
        config = _deep_merge(config, overrides)
    _validate(config)
    return config
