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
