"""Node types. Each wraps an existing stage function; no stage logic lives here.

Ports carry file paths (the stages already exchange CSV/JSON files). A port type names the
kind of file, so only compatible stages can be wired. A param whose default is None is
required. Approval gates (O3 PCU table, O4 congestion weights, O6 stopped-speed threshold)
are enforced by the stages themselves from their config files; the graph never bypasses
them, and ``allow_draft`` is off unless the graph file turns it on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from pattom.paths import CALIBRATION, REPO_ROOT


@dataclass(frozen=True)
class Port:
    name: str
    type: str


@dataclass(frozen=True)
class NodeType:
    name: str
    label: str
    inputs: tuple[Port, ...] = ()
    outputs: tuple[Port, ...] = ()
    params: dict[str, Any] = field(default_factory=dict)
    run: Callable[[dict[str, Any], dict[str, Any]], dict[str, str]] | None = None
    required: tuple[str, ...] = ()  # params that must be set in the graph file (default is None)

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "inputs": [vars(p) for p in self.inputs],
            "outputs": [vars(p) for p in self.outputs],
            "params": self.params,
            "required": list(self.required),
        }


def _path(value: str | Path) -> Path:
    p = Path(value)
    return p if p.is_absolute() else REPO_ROOT / p


def _cfg(name: str) -> str:
    return str(REPO_ROOT / "configs" / name)


def _cfr(inputs, p):
    from pattom.prepare import to_cfr

    to_cfr(_path(p["video"]), _path(p["out"]), p["fps"], p["slot"])
    return {"video": str(_path(p["out"]))}


def _undistort(inputs, p):
    from pattom.prepare import LensCalibration, undistort_video

    undistort_video(_path(inputs["video"]), _path(p["out"]), LensCalibration.load(_path(p["lens"])), p["slot"])
    return {"video": str(_path(p["out"]))}


def _detect(inputs, p):
    from pattom.detection import DetectionConfig, run_detection

    return {"detections": str(run_detection(_path(inputs["video"]), p["slot"], DetectionConfig.load(_path(p["config"]))))}


def _track(inputs, p):
    from pattom.tracking import TrackerConfig, run_tracking

    return {"tracks": str(run_tracking(_path(inputs["detections"]), TrackerConfig.load(_path(p["config"]))))}


def _ground(inputs, p):
    from pattom.ground import GroundCalibration, map_tracks

    cal = GroundCalibration.from_config(_path(p["config"]))
    return {"tracks": str(map_tracks(_path(inputs["tracks"]), cal))}


def _count(inputs, p):
    from pattom.counting import run_counting

    return {"counts": str(run_counting(_path(inputs["tracks"]), _path(p["lines"]), p["interval_s"], p["offset_s"]))}


def _delay(inputs, p):
    from pattom.delay import run_delay_queue

    signal_log = _path(p["signal_log"]) if p["signal_log"] else None
    return {"delays": str(run_delay_queue(_path(inputs["tracks"]), _path(p["definitions"]), p["interval_s"],
                                          signal_log, p["offset_s"], p["allow_draft"]))}


def _emissions(inputs, p):
    from pattom.emissions import run_emissions

    vehicle_delay = _path(inputs["delays"]).parent / "vehicle_delay.csv"
    return {"emissions": str(run_emissions(vehicle_delay, _path(p["config"]), p["interval_s"], p["offset_s"]))}


def _indicators(inputs, p):
    from pattom.indicators import run_indicators

    run_dir = _path(inputs["counts"]).parent
    if _path(inputs["delays"]).parent != run_dir:
        raise ValueError("counts and delays come from different run folders")
    return {"indicators": str(run_indicators(run_dir, _path(p["config"]), _path(p["signal_log"])))}


def _congestion(inputs, p):
    from pattom.congestion import run_congestion

    return {"index": str(run_congestion(_path(inputs["indicators"]), _path(p["formula"])))}


_P = Port
_TYPES = [
    NodeType("cfr", "Constant-frame-rate copy (B)", (), (_P("video", "video"),),
             {"video": None, "out": None, "fps": 30.0, "slot": None}, _cfr, ("video", "out", "slot")),
    NodeType("undistort", "Undistort (B)", (_P("video", "video"),), (_P("video", "video"),),
             {"out": None, "lens": str(CALIBRATION / "lens.json"), "slot": None}, _undistort, ("out", "slot")),
    NodeType("detect", "YOLO detection (C)", (_P("video", "video"),), (_P("detections", "detections"),),
             {"slot": None, "config": _cfg("detection.yaml")}, _detect, ("slot",)),
    NodeType("track", "ByteTrack (D)", (_P("detections", "detections"),), (_P("tracks", "tracks"),),
             {"config": _cfg("tracker.yaml")}, _track),
    NodeType("ground", "Ground mapping (F)", (_P("tracks", "tracks"),), (_P("tracks", "tracks"),),
             {"config": str(CALIBRATION / "ground.yaml")}, _ground),
    NodeType("count", "Counting (F)", (_P("tracks", "tracks"),), (_P("counts", "counts"),),
             {"lines": _cfg("lines.yaml"), "interval_s": 900.0, "offset_s": 0.0}, _count),
    NodeType("delay_queue", "Stopped delay and queue (F)", (_P("tracks", "tracks"),), (_P("delays", "delays"),),
             {"definitions": _cfg("definitions.yaml"), "signal_log": None, "interval_s": 900.0,
              "offset_s": 0.0, "allow_draft": False}, _delay),
    NodeType("emissions", "Idle CO2 estimate (G)", (_P("delays", "delays"),), (_P("emissions", "emissions"),),
             {"config": _cfg("emissions.yaml"), "interval_s": 900.0, "offset_s": 0.0}, _emissions),
    NodeType("indicators", "Volume, capacity, V/C (F)", (_P("counts", "counts"), _P("delays", "delays")),
             (_P("indicators", "indicators"),), {"config": _cfg("indicators.yaml"), "signal_log": None}, _indicators, ("signal_log",)),
    NodeType("congestion", "Congestion index (G)", (_P("indicators", "indicators"),), (_P("index", "index"),),
             {"formula": _cfg("congestion.yaml")}, _congestion),
]
NODE_TYPES: dict[str, NodeType] = {t.name: t for t in _TYPES}
