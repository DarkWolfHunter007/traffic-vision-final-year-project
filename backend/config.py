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
    "speed": {
        "smoothing_method": "moving_average",
        "smoothing_window_s": 0.5,
        "min_track_points": 3,
        "max_gap_seconds": 1.0,
        "min_displacement_m": 0.1,
        "max_plausible_speed_mps": 45.0,
        "ground_point_method": "bottom_center",
    },
    "queue": {
        "stop_speed_threshold_kmh": 5.0,
        "min_stop_duration_s": 3.0,
        "min_queue_vehicles": 2,
        "aggregation_interval_s": 1.0,
        "max_gap_seconds": 1.0,
        "stop_line_mapping": {},
    },
    "review": {
        "confidence_threshold": 0.50,
        "snippet_before_s": 1.0,
        "snippet_after_s": 1.0,
        "allowed_classes": [
            "car",
            "bus",
            "truck",
            "motorcycle",
            "auto_rickshaw",
        ],
        "review_statuses": ["pending", "approved", "rejected"],
        "output_dir": "data/processed/review_snippets",
    },
    "active_learning": {
        "output_dir": "data/processed/datasets",
        "default_version": "v1",
        "split_strategy": "time_block",
        "time_block_duration_s": 300.0,
        "split_ratios": {"train": 0.8, "val": 0.2, "test": 0.0},
        "seed": 42,
        "duplicate_policy": "latest_review",
        "class_mapping": {
            "car": 0,
            "bus": 1,
            "truck": 2,
            "motorcycle": 3,
            "auto_rickshaw": 4,
        },
        "min_frame_interval_s": 0.0,
        "export_images": True,
    },
    "evaluation": {
        "iou_threshold": 0.5,
        "map_iou_thresholds": [0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95],
        "confidence_threshold": 0.25,
        "held_out_split": "val",
        "counting_tolerance_pct": 10.0,
        "output_dir": "data/processed/evaluations",
    },
    "export": {
        "output_dir": "data/processed/exports",
        "formats": ["csv", "json", "sqlite"],
        "default_format": "all",
        "include_raw_events": True,
    },
    "dashboard": {
        "host": "127.0.0.1",
        "port": 8000,
        "summary_interval_s": 900.0,
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
    speed = config.get("speed")
    if speed is not None:
        if not isinstance(speed, Mapping):
            raise ConfigError("speed must be a mapping")
        smoothing_method = speed.get("smoothing_method")
        if smoothing_method not in {"moving_average", "none"}:
            raise ConfigError("speed.smoothing_method must be either 'moving_average' or 'none'")
        window_s = speed.get("smoothing_window_s")
        if not (isinstance(window_s, (int, float)) and window_s >= 0):
            raise ConfigError("speed.smoothing_window_s must be a non-negative number")
        min_pts = speed.get("min_track_points")
        if not (isinstance(min_pts, int) and min_pts >= 2):
            raise ConfigError("speed.min_track_points must be an integer >= 2")
        max_gap = speed.get("max_gap_seconds")
        if not (isinstance(max_gap, (int, float)) and max_gap > 0):
            raise ConfigError("speed.max_gap_seconds must be a positive number")
        min_disp = speed.get("min_displacement_m")
        if not (isinstance(min_disp, (int, float)) and min_disp >= 0):
            raise ConfigError("speed.min_displacement_m must be a non-negative number")
        max_speed = speed.get("max_plausible_speed_mps")
        if not (isinstance(max_speed, (int, float)) and max_speed > 0):
            raise ConfigError("speed.max_plausible_speed_mps must be a positive number")
        ground_method = speed.get("ground_point_method")
        if ground_method != "bottom_center":
            raise ConfigError("Phase 08 requires speed.ground_point_method to be 'bottom_center'")
    queue = config.get("queue")
    if queue is not None:
        if not isinstance(queue, Mapping):
            raise ConfigError("queue must be a mapping")
        speed_thresh = queue.get("stop_speed_threshold_kmh")
        if not (isinstance(speed_thresh, (int, float)) and speed_thresh > 0):
            raise ConfigError("queue.stop_speed_threshold_kmh must be a positive number")
        min_duration = queue.get("min_stop_duration_s")
        if not (isinstance(min_duration, (int, float)) and min_duration >= 0):
            raise ConfigError("queue.min_stop_duration_s must be a non-negative number")
        min_vehicles = queue.get("min_queue_vehicles")
        if not (isinstance(min_vehicles, int) and min_vehicles >= 1):
            raise ConfigError("queue.min_queue_vehicles must be an integer >= 1")
        agg_interval = queue.get("aggregation_interval_s")
        if not (isinstance(agg_interval, (int, float)) and agg_interval > 0):
            raise ConfigError("queue.aggregation_interval_s must be a positive number")
        max_gap = queue.get("max_gap_seconds")
        if not (isinstance(max_gap, (int, float)) and max_gap > 0):
            raise ConfigError("queue.max_gap_seconds must be a positive number")
        stop_lines = queue.get("stop_line_mapping")
        if stop_lines is not None and not isinstance(stop_lines, Mapping):
            raise ConfigError("queue.stop_line_mapping must be a mapping")
    review = config.get("review")
    if review is not None:
        if not isinstance(review, Mapping):
            raise ConfigError("review must be a mapping")
        conf_thresh = review.get("confidence_threshold")
        if not (isinstance(conf_thresh, (int, float)) and 0.0 <= conf_thresh <= 1.0):
            raise ConfigError("review.confidence_threshold must be a number between 0.0 and 1.0")
        snippet_before = review.get("snippet_before_s")
        if not (isinstance(snippet_before, (int, float)) and snippet_before >= 0):
            raise ConfigError("review.snippet_before_s must be a non-negative number")
        snippet_after = review.get("snippet_after_s")
        if not (isinstance(snippet_after, (int, float)) and snippet_after >= 0):
            raise ConfigError("review.snippet_after_s must be a non-negative number")
        allowed_classes = review.get("allowed_classes")
        if not isinstance(allowed_classes, list) or not all(isinstance(c, str) and c.strip() for c in allowed_classes):
            raise ConfigError("review.allowed_classes must be a list of non-empty strings")
        review_statuses = review.get("review_statuses")
        if not isinstance(review_statuses, list) or not all(isinstance(s, str) and s.strip() for s in review_statuses):
            raise ConfigError("review.review_statuses must be a list of non-empty strings")
        for required_status in ("pending", "approved", "rejected"):
            if required_status not in review_statuses:
                raise ConfigError(f"review.review_statuses must include '{required_status}'")
        output_dir = review.get("output_dir")
        if not isinstance(output_dir, str) or not output_dir.strip():
            raise ConfigError("review.output_dir must be a non-empty string")
    al = config.get("active_learning")
    if al is not None:
        if not isinstance(al, Mapping):
            raise ConfigError("active_learning must be a mapping")
        out_dir = al.get("output_dir")
        if not isinstance(out_dir, str) or not out_dir.strip():
            raise ConfigError("active_learning.output_dir must be a non-empty string")
        def_ver = al.get("default_version")
        if not isinstance(def_ver, str) or not def_ver.strip():
            raise ConfigError("active_learning.default_version must be a non-empty string")
        strat = al.get("split_strategy")
        if strat not in ("video", "time_block"):
            raise ConfigError("active_learning.split_strategy must be 'video' or 'time_block'")
        dur = al.get("time_block_duration_s")
        if not (isinstance(dur, (int, float)) and dur > 0):
            raise ConfigError("active_learning.time_block_duration_s must be a positive number")
        ratios = al.get("split_ratios")
        if not isinstance(ratios, Mapping):
            raise ConfigError("active_learning.split_ratios must be a mapping")
        for split_name, ratio in ratios.items():
            if not isinstance(split_name, str) or not (isinstance(ratio, (int, float)) and 0.0 <= ratio <= 1.0):
                raise ConfigError(f"active_learning.split_ratios value for '{split_name}' must be between 0.0 and 1.0")
        if sum(float(r) for r in ratios.values()) <= 0:
            raise ConfigError("active_learning.split_ratios sum must be greater than 0")
        seed = al.get("seed")
        if not isinstance(seed, int):
            raise ConfigError("active_learning.seed must be an integer")
        dup_policy = al.get("duplicate_policy")
        if dup_policy not in ("latest_review", "keep_all"):
            raise ConfigError("active_learning.duplicate_policy must be 'latest_review' or 'keep_all'")
        cmap = al.get("class_mapping")
        if not isinstance(cmap, Mapping) or not cmap:
            raise ConfigError("active_learning.class_mapping must be a non-empty mapping")
        for cls_name, cls_id in cmap.items():
            if not isinstance(cls_name, str) or not (isinstance(cls_id, int) and cls_id >= 0):
                raise ConfigError(f"active_learning.class_mapping invalid entry: {cls_name}: {cls_id}")
        min_gap = al.get("min_frame_interval_s")
        if not (isinstance(min_gap, (int, float)) and min_gap >= 0):
            raise ConfigError("active_learning.min_frame_interval_s must be a non-negative number")
        export_img = al.get("export_images")
        if not isinstance(export_img, bool):
            raise ConfigError("active_learning.export_images must be a boolean")
    ev = config.get("evaluation")
    if ev is not None:
        if not isinstance(ev, Mapping):
            raise ConfigError("evaluation must be a mapping")
        iou = ev.get("iou_threshold")
        if not (isinstance(iou, (int, float)) and 0.0 <= iou <= 1.0):
            raise ConfigError("evaluation.iou_threshold must be between 0.0 and 1.0")
        map_ious = ev.get("map_iou_thresholds")
        if not isinstance(map_ious, (list, tuple)) or not map_ious:
            raise ConfigError("evaluation.map_iou_thresholds must be a non-empty list of numbers")
        for val in map_ious:
            if not (isinstance(val, (int, float)) and 0.0 <= val <= 1.0):
                raise ConfigError("evaluation.map_iou_thresholds values must be between 0.0 and 1.0")
        conf = ev.get("confidence_threshold")
        if not (isinstance(conf, (int, float)) and 0.0 <= conf <= 1.0):
            raise ConfigError("evaluation.confidence_threshold must be between 0.0 and 1.0")
        split = ev.get("held_out_split")
        if split not in ("val", "test"):
            raise ConfigError("evaluation.held_out_split must be 'val' or 'test'")
        tol = ev.get("counting_tolerance_pct")
        if not (isinstance(tol, (int, float)) and tol > 0):
            raise ConfigError("evaluation.counting_tolerance_pct must be a positive number")
        out_dir = ev.get("output_dir")
        if not isinstance(out_dir, str) or not out_dir.strip():
            raise ConfigError("evaluation.output_dir must be a non-empty string")
    exp = config.get("export")
    if exp is not None:
        if not isinstance(exp, Mapping):
            raise ConfigError("export must be a mapping")
        out_dir = exp.get("output_dir")
        if not isinstance(out_dir, str) or not out_dir.strip():
            raise ConfigError("export.output_dir must be a non-empty string")
        formats = exp.get("formats")
        allowed_formats = {"csv", "json", "sqlite"}
        if not isinstance(formats, (list, tuple)) or not formats:
            raise ConfigError("export.formats must be a non-empty list of format strings")
        for fmt in formats:
            if fmt not in allowed_formats:
                raise ConfigError(f"export.formats contains invalid format '{fmt}'; allowed: {sorted(allowed_formats)}")
        def_fmt = exp.get("default_format")
        if def_fmt not in {"all", "csv", "json", "sqlite"}:
            raise ConfigError("export.default_format must be one of 'all', 'csv', 'json', 'sqlite'")
        if "include_raw_events" in exp and not isinstance(exp["include_raw_events"], bool):
            raise ConfigError("export.include_raw_events must be a boolean")
    dash = config.get("dashboard")
    if dash is not None:
        if not isinstance(dash, Mapping):
            raise ConfigError("dashboard must be a mapping")
        host = dash.get("host")
        if not isinstance(host, str) or not host.strip():
            raise ConfigError("dashboard.host must be a non-empty string")
        port = dash.get("port")
        if not (isinstance(port, int) and 1 <= port <= 65535):
            raise ConfigError("dashboard.port must be an integer between 1 and 65535")
        interval = dash.get("summary_interval_s")
        if not (isinstance(interval, (int, float)) and interval > 0):
            raise ConfigError("dashboard.summary_interval_s must be a positive number")



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
