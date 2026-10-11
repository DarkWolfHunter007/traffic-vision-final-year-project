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
