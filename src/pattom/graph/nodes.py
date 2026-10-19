"""Node types. Each wraps an existing stage function; no stage logic lives here.

Ports carry file paths (the stages already exchange CSV/JSON files). A port type names the
kind of file, so only compatible stages can be wired. A param whose default is None is
required. Approval gates (O3 PCU table, O4 congestion weights, O6 stopped-speed threshold)
are enforced by the stages themselves from their config files; the graph never bypasses
them, and ``allow_draft`` is off unless the graph file turns it on.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from pattom.paths import CALIBRATION, REPO_ROOT

PORT_COLORS: dict[str, str] = {
    "video": "#8b5cf6",       # Purple
    "detections": "#f59e0b",  # Amber
    "tracks": "#06b6d4",      # Cyan
    "counts": "#10b981",      # Emerald
    "delays": "#ef4444",      # Red
    "emissions": "#f97316",   # Orange
    "indicators": "#3b82f6",  # Blue
    "index": "#14b8a6",       # Teal
}


@dataclass(frozen=True)
class Port:
    name: str
    type: str

    @property
    def color(self) -> str:
        return PORT_COLORS.get(self.type, "#6b7280")


def _path(value: str | Path | None) -> Path:
    if not value:
        return Path()
    p = Path(value)
    return p if p.is_absolute() else REPO_ROOT / p


def _cfg(name: str) -> str:
    return str(REPO_ROOT / "configs" / name)


def check_gate_o6(params: dict[str, Any]) -> dict[str, Any]:
    """Check approval gate O6 (queue definition & stopped-speed threshold)."""
    cfg_file = _path(params.get("definitions") or _cfg("definitions.yaml"))
    allow_draft = bool(params.get("allow_draft", False))
    rel_path = str(cfg_file.relative_to(REPO_ROOT) if cfg_file.is_relative_to(REPO_ROOT) else cfg_file)
    if not cfg_file.exists():
        return {
            "locked": True,
            "decision": "O6",
            "title": "Queue & Stopped-Speed Threshold (O6)",
            "config": rel_path,
            "reason": "Stopped-speed threshold and queue definition (T46/O6) not set yet. Config file missing.",
            "version": None,
            "approved": False,
            "allow_draft": allow_draft,
        }
    try:
        data = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}
        approved = bool(data.get("approved", False))
        version = data.get("definition_version")
        stopped_speed = data.get("stopped_speed_kmh")
        speed_window = data.get("speed_window_s")
        max_gap = data.get("max_gap_s")
        approaches = data.get("approaches")

        required_fields = ["stopped_speed_kmh", "speed_window_s", "max_gap_s"]
        empty_fields = [k for k in required_fields if data.get(k) is None]
        if empty_fields:
            return {
                "locked": True,
                "decision": "O6",
                "title": "Queue & Stopped-Speed Threshold (O6)",
                "config": rel_path,
                "reason": f"Operational definitions (T46/O6) not set yet ({', '.join(empty_fields)}). Fill in {rel_path}.",
                "version": version,
                "approved": False,
                "allow_draft": allow_draft,
            }
        if not approaches:
            return {
                "locked": True,
                "decision": "O6",
                "title": "Queue & Stopped-Speed Threshold (O6)",
                "config": rel_path,
                "reason": f"No approach zones defined in {rel_path}.",
                "version": version,
                "approved": False,
                "allow_draft": allow_draft,
            }
        if not approved:
            return {
                "locked": not allow_draft,
                "decision": "O6",
                "title": "Queue & Stopped-Speed Threshold (O6)",
                "config": rel_path,
                "reason": f"Definitions ({version}) are not approved yet (approved: false). Approve in {rel_path} or enable Allow Draft.",
                "version": version,
                "approved": False,
                "allow_draft": allow_draft,
            }
        return {
            "locked": False,
            "decision": "O6",
            "title": "Queue & Stopped-Speed Threshold (O6)",
            "config": rel_path,
            "reason": f"Approved (version {version})",
            "version": version,
            "approved": True,
            "allow_draft": allow_draft,
        }
    except Exception as e:
        return {
            "locked": True,
            "decision": "O6",
            "title": "Queue & Stopped-Speed Threshold (O6)",
            "config": rel_path,
            "reason": f"Config read error: {e}",
            "version": None,
            "approved": False,
            "allow_draft": allow_draft,
        }


def check_gate_o3(params: dict[str, Any]) -> dict[str, Any]:
    """Check approval gate O3 (PCU table and approach widths)."""
    cfg_file = _path(params.get("config") or _cfg("indicators.yaml"))
    rel_path = str(cfg_file.relative_to(REPO_ROOT) if cfg_file.is_relative_to(REPO_ROOT) else cfg_file)
    if not cfg_file.exists():
        return {
            "locked": True,
            "decision": "O3",
            "title": "PCU Table & Approach Widths (O3)",
            "config": rel_path,
            "reason": "PCU table selection (O3) and approach widths not set yet. Config file missing.",
            "version": None,
            "approved": False,
        }
    try:
        data = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}
        pcu_table = data.get("pcu_table")
        if pcu_table not in ("table_3_1", "table_III_1"):
            return {
                "locked": True,
                "decision": "O3",
                "title": "PCU Table & Approach Widths (O3)",
                "config": rel_path,
                "reason": "PCU table selection (O3) not set yet (must be table_3_1 or table_III_1).",
                "version": None,
                "approved": False,
            }
        apps = data.get("approaches", {})
        if not apps:
            return {
                "locked": True,
                "decision": "O3",
                "title": "PCU Table & Approach Widths (O3)",
                "config": rel_path,
                "reason": "Approach widths (measured on site) not set yet in configs/indicators.yaml.",
                "version": None,
                "approved": False,
            }
        for name, a in apps.items():
            if not isinstance(a, dict) or a.get("width_m") is None:
                return {
                    "locked": True,
                    "decision": "O3",
                    "title": "PCU Table & Approach Widths (O3)",
                    "config": rel_path,
                    "reason": f"Approach width for {name} not set yet in configs/indicators.yaml.",
                    "version": None,
                    "approved": False,
                }
        return {
            "locked": False,
            "decision": "O3",
            "title": "PCU Table & Approach Widths (O3)",
            "config": rel_path,
            "reason": f"Selected PCU table: {pcu_table}",
            "version": pcu_table,
            "approved": True,
        }
    except Exception as e:
        return {
            "locked": True,
            "decision": "O3",
            "title": "PCU Table & Approach Widths (O3)",
            "config": rel_path,
            "reason": f"Config read error: {e}",
            "version": None,
            "approved": False,
        }


def check_gate_o4(params: dict[str, Any]) -> dict[str, Any]:
    """Check approval gate O4 (congestion index formula and weights)."""
    cfg_file = _path(params.get("formula") or _cfg("congestion.yaml"))
    rel_path = str(cfg_file.relative_to(REPO_ROOT) if cfg_file.is_relative_to(REPO_ROOT) else cfg_file)
    if not cfg_file.exists():
        return {
            "locked": True,
            "decision": "O4",
            "title": "Congestion Index Formula & Weights (O4)",
            "config": rel_path,
            "reason": "Congestion index formula and weights (O4) need guide approval. Config file missing.",
            "version": None,
            "approved": False,
        }
    try:
        data = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}
        approved = bool(data.get("approved", False))
        version = data.get("formula_version")
        inds = data.get("indicators", [])
        if not inds:
            return {
                "locked": True,
                "decision": "O4",
                "title": "Congestion Index Formula & Weights (O4)",
                "config": rel_path,
                "reason": "No indicators defined in congestion formula.",
                "version": version,
                "approved": False,
            }
        for i in inds:
            if not isinstance(i, dict) or i.get("weight") is None:
                return {
                    "locked": True,
                    "decision": "O4",
                    "title": "Congestion Index Formula & Weights (O4)",
                    "config": rel_path,
                    "reason": f"Weight for indicator {i.get('column')} not set yet (O4 needs guide approval).",
                    "version": version,
                    "approved": False,
                }
        total = sum(float(i["weight"]) for i in inds)
        if not math.isclose(total, 1.0, abs_tol=1e-9):
            return {
                "locked": True,
                "decision": "O4",
                "title": "Congestion Index Formula & Weights (O4)",
                "config": rel_path,
                "reason": f"Weights sum to {total:.3f}, not 1.0.",
                "version": version,
                "approved": False,
            }
        if not approved:
            return {
                "locked": True,
                "decision": "O4",
                "title": "Congestion Index Formula & Weights (O4)",
                "config": rel_path,
                "reason": "Congestion index formula and weights (O4) need guide approval (approved: false).",
                "version": version,
                "approved": False,
            }
        return {
            "locked": False,
            "decision": "O4",
            "title": "Congestion Index Formula & Weights (O4)",
            "config": rel_path,
            "reason": f"Approved (version {version})",
            "version": version,
            "approved": True,
        }
    except Exception as e:
        return {
            "locked": True,
            "decision": "O4",
            "title": "Congestion Index Formula & Weights (O4)",
            "config": rel_path,
            "reason": f"Config read error: {e}",
            "version": None,
            "approved": False,
        }


@dataclass(frozen=True)
class NodeType:
    name: str
    label: str
    category: str = "General"
    inputs: tuple[Port, ...] = ()
    outputs: tuple[Port, ...] = ()
    params: dict[str, Any] = field(default_factory=dict)
    run: Callable[[dict[str, Any], dict[str, Any]], dict[str, str]] | None = None
    required: tuple[str, ...] = ()  # params that must be set in the graph file (default is None)
    param_schema: dict[str, Any] = field(default_factory=dict)
    gate_checker: Callable[[dict[str, Any]], dict[str, Any]] | None = None

    def describe(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        merged_params = {**self.params, **(params or {})}
        gate_status = self.gate_checker(merged_params) if self.gate_checker else None
        return {
            "name": self.name,
            "label": self.label,
            "category": self.category,
            "inputs": [{"name": p.name, "type": p.type, "color": p.color} for p in self.inputs],
            "outputs": [{"name": p.name, "type": p.type, "color": p.color} for p in self.outputs],
            "params": self.params,
            "required": list(self.required),
            "param_schema": self.param_schema,
            "gate": gate_status,
        }


def _cfr(inputs, p):
    from pattom.prepare import to_cfr

    to_cfr(_path(p["video"]), _path(p["out"]), float(p["fps"]), str(p["slot"]))
    return {"video": str(_path(p["out"]))}


def _undistort(inputs, p):
    from pattom.prepare import LensCalibration, undistort_video

    undistort_video(_path(inputs["video"]), _path(p["out"]), LensCalibration.load(_path(p["lens"])), str(p["slot"]))
    return {"video": str(_path(p["out"]))}


def _detect(inputs, p):
    from pattom.detection import DetectionConfig, run_detection

    return {"detections": str(run_detection(_path(inputs["video"]), str(p["slot"]), DetectionConfig.load(_path(p["config"]))))}


def _track(inputs, p):
    from pattom.tracking import TrackerConfig, run_tracking

    return {"tracks": str(run_tracking(_path(inputs["detections"]), TrackerConfig.load(_path(p["config"]))))}


def _ground(inputs, p):
    from pattom.ground import GroundCalibration, map_tracks

    cal = GroundCalibration.from_config(_path(p["config"]))
    return {"tracks": str(map_tracks(_path(inputs["tracks"]), cal))}


def _count(inputs, p):
    from pattom.counting import run_counting

    return {"counts": str(run_counting(_path(inputs["tracks"]), _path(p["lines"]), float(p["interval_s"]), float(p["offset_s"])))}


def _delay(inputs, p):
    from pattom.delay import run_delay_queue

    sig_raw = p.get("signal_log")
    signal_log = _path(sig_raw) if sig_raw else None
    return {"delays": str(run_delay_queue(_path(inputs["tracks"]), _path(p["definitions"]), float(p["interval_s"]),
                                          signal_log, float(p["offset_s"]), bool(p.get("allow_draft", False))))}


def _emissions(inputs, p):
    from pattom.emissions import run_emissions

    vehicle_delay = _path(inputs["delays"]).parent / "vehicle_delay.csv"
    return {"emissions": str(run_emissions(vehicle_delay, _path(p["config"]), float(p["interval_s"]), float(p["offset_s"])))}


def _indicators(inputs, p):
    from pattom.indicators import run_indicators

    run_dir = _path(inputs["counts"]).parent
    if _path(inputs["delays"]).parent != run_dir:
        raise ValueError("counts and delays come from different run folders")
    sig_raw = p.get("signal_log")
    if not sig_raw:
        raise ValueError("indicators stage requires a signal_log file (e.g. read from footage)")
    return {"indicators": str(run_indicators(run_dir, _path(p["config"]), _path(sig_raw)))}


def _congestion(inputs, p):
    from pattom.congestion import run_congestion

    return {"index": str(run_congestion(_path(inputs["indicators"]), _path(p["formula"])))}


_P = Port
_TYPES = [
    NodeType(
        name="cfr",
        label="Constant-frame-rate copy (B)",
        category="Preparation",
        inputs=(),
        outputs=(_P("video", "video"),),
        params={"video": None, "out": None, "fps": 30.0, "slot": None},
        run=_cfr,
        required=("video", "out", "slot"),
        param_schema={
            "video": {"type": "file", "label": "Source Video", "filter": [".mov", ".mp4", ".MOV", ".MP4"], "placeholder": "data/raw/IMG_1480.MOV", "required": True},
            "out": {"type": "file", "label": "Output MP4 Path", "filter": [".mp4"], "placeholder": "data/cfr/IMG_1480.mp4", "required": True},
            "fps": {"type": "number", "label": "Frame Rate (fps)", "default": 30.0, "min": 1.0, "max": 120.0, "step": 1.0, "required": True},
            "slot": {"type": "text", "label": "Slot Name", "suggestions": ["test", "offpeak", "peak"], "placeholder": "test", "required": True},
        },
    ),
    NodeType(
        name="undistort",
        label="Undistort (B)",
        category="Preparation",
        inputs=(_P("video", "video"),),
        outputs=(_P("video", "video"),),
        params={"out": None, "lens": str(CALIBRATION / "lens.json"), "slot": None},
        run=_undistort,
        required=("out", "slot"),
        param_schema={
            "out": {"type": "file", "label": "Output MP4 Path", "filter": [".mp4"], "placeholder": "data/undistorted/IMG_1480.mp4", "required": True},
            "lens": {"type": "file", "label": "Lens Calibration JSON", "filter": [".json"], "default": str(CALIBRATION / "lens.json"), "required": True},
            "slot": {"type": "text", "label": "Slot Name", "suggestions": ["test", "offpeak", "peak"], "placeholder": "test", "required": True},
        },
    ),
    NodeType(
        name="detect",
        label="YOLO detection (C)",
        category="Perception",
        inputs=(_P("video", "video"),),
        outputs=(_P("detections", "detections"),),
        params={"slot": None, "config": _cfg("detection.yaml")},
        run=_detect,
        required=("slot",),
        param_schema={
            "slot": {"type": "text", "label": "Slot Name", "suggestions": ["test", "offpeak", "peak"], "placeholder": "test", "required": True},
            "config": {"type": "file", "label": "Detection Config YAML", "filter": [".yaml", ".yml"], "default": _cfg("detection.yaml"), "required": True},
        },
    ),
    NodeType(
        name="track",
        label="ByteTrack (D)",
        category="Perception",
        inputs=(_P("detections", "detections"),),
        outputs=(_P("tracks", "tracks"),),
        params={"config": _cfg("tracker.yaml")},
        run=_track,
        required=(),
        param_schema={
            "config": {"type": "file", "label": "Tracker Config YAML", "filter": [".yaml", ".yml"], "default": _cfg("tracker.yaml"), "required": True},
        },
    ),
    NodeType(
        name="ground",
        label="Ground mapping (F)",
        category="Measurements",
        inputs=(_P("tracks", "tracks"),),
        outputs=(_P("tracks", "tracks"),),
        params={"config": str(CALIBRATION / "ground.yaml")},
        run=_ground,
        required=(),
        param_schema={
            "config": {"type": "file", "label": "Ground Calibration YAML", "filter": [".yaml", ".yml"], "default": str(CALIBRATION / "ground.yaml"), "required": True},
        },
    ),
    NodeType(
        name="count",
        label="Counting (F)",
        category="Measurements",
        inputs=(_P("tracks", "tracks"),),
        outputs=(_P("counts", "counts"),),
        params={"lines": _cfg("lines.yaml"), "interval_s": 900.0, "offset_s": 0.0},
        run=_count,
        required=(),
        param_schema={
            "lines": {"type": "file", "label": "Counting Lines YAML", "filter": [".yaml", ".yml"], "default": _cfg("lines.yaml"), "required": True},
            "interval_s": {"type": "number", "label": "Interval Length (s)", "default": 900.0, "min": 10.0, "step": 60.0, "required": True},
            "offset_s": {"type": "number", "label": "Offset (s)", "default": 0.0, "min": 0.0, "step": 1.0, "required": True},
        },
    ),
    NodeType(
        name="delay_queue",
        label="Stopped delay and queue (F)",
        category="Traffic Parameters",
        inputs=(_P("tracks", "tracks"),),
        outputs=(_P("delays", "delays"),),
        params={"definitions": _cfg("definitions.yaml"), "signal_log": None, "interval_s": 900.0,
                "offset_s": 0.0, "allow_draft": False},
        run=_delay,
        required=(),
        param_schema={
            "definitions": {"type": "file", "label": "Definitions YAML (T46/O6)", "filter": [".yaml", ".yml"], "default": _cfg("definitions.yaml"), "required": True},
            "signal_log": {"type": "file", "label": "Signal Log CSV (optional for queue)", "filter": [".csv"], "placeholder": "configs/signal_log.csv", "required": False},
            "interval_s": {"type": "number", "label": "Interval Length (s)", "default": 900.0, "min": 10.0, "step": 60.0, "required": True},
            "offset_s": {"type": "number", "label": "Offset (s)", "default": 0.0, "min": 0.0, "step": 1.0, "required": True},
            "allow_draft": {"type": "boolean", "label": "Allow Unapproved Draft", "default": False, "description": "Run with draft definitions (outputs labelled draft)"},
        },
        gate_checker=check_gate_o6,
    ),
    NodeType(
        name="emissions",
        label="Idle CO2 estimate (G)",
        category="Analysis & Emissions",
        inputs=(_P("delays", "delays"),),
        outputs=(_P("emissions", "emissions"),),
        params={"config": _cfg("emissions.yaml"), "interval_s": 900.0, "offset_s": 0.0},
        run=_emissions,
        required=(),
        param_schema={
            "config": {"type": "file", "label": "Emissions Config YAML", "filter": [".yaml", ".yml"], "default": _cfg("emissions.yaml"), "required": True},
            "interval_s": {"type": "number", "label": "Interval Length (s)", "default": 900.0, "min": 10.0, "step": 60.0, "required": True},
            "offset_s": {"type": "number", "label": "Offset (s)", "default": 0.0, "min": 0.0, "step": 1.0, "required": True},
        },
    ),
    NodeType(
        name="indicators",
        label="Volume, capacity, V/C (F)",
        category="Traffic Parameters",
        inputs=(_P("counts", "counts"), _P("delays", "delays")),
        outputs=(_P("indicators", "indicators"),),
        params={"config": _cfg("indicators.yaml"), "signal_log": _cfg("signal_log.csv")},
        run=_indicators,
        required=(),
        param_schema={
            "config": {"type": "file", "label": "Indicators Config YAML (O3)", "filter": [".yaml", ".yml"], "default": _cfg("indicators.yaml"), "required": True},
            "signal_log": {"type": "file", "label": "Signal Log CSV", "filter": [".csv"], "default": _cfg("signal_log.csv"), "placeholder": "configs/signal_log.csv", "required": True},
        },
        gate_checker=check_gate_o3,
    ),
    NodeType(
        name="congestion",
        label="Congestion index (G)",
        category="Analysis & Emissions",
        inputs=(_P("indicators", "indicators"),),
        outputs=(_P("index", "index"),),
        params={"formula": _cfg("congestion.yaml")},
        run=_congestion,
        required=(),
        param_schema={
            "formula": {"type": "file", "label": "Congestion Formula YAML (O4)", "filter": [".yaml", ".yml"], "default": _cfg("congestion.yaml"), "required": True},
        },
        gate_checker=check_gate_o4,
    ),
]
NODE_TYPES: dict[str, NodeType] = {t.name: t for t in _TYPES}
