"""Click-to-calibrate helpers for the editor (calibrate.html).

The user clicks points on a video frame and types the distances measured on
the road. This module checks the input with the project's own code and writes
the local config files. It adds no values: every number comes from a click or
from the user. Metres are only computed through a fitted ground mapping that
has a check error (ground.py); never from raw pixels.

Files written (all local, gitignored): calibration/ground.yaml,
configs/lines.yaml, configs/definitions.yaml (approach zones only) and
configs/indicators.yaml (approach widths only).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import yaml

from pattom.ground import fit_mapping, to_ground
from pattom.paths import CALIBRATION, REPO_ROOT
from pattom.runmeta import sha256_file

CONFIGS = REPO_ROOT / "configs"
GROUND_FILE = CALIBRATION / "ground.yaml"
LINES_FILE = CONFIGS / "lines.yaml"
DEFINITIONS_FILE = CONFIGS / "definitions.yaml"
INDICATORS_FILE = CONFIGS / "indicators.yaml"

LINE_TYPES = ("stop_line", "arrival", "exit")
DIRECTIONS = ("left", "right", "both")
APPROACHES = ("north", "south", "east", "west")


class CalibrationError(ValueError):
    """Bad user input; the message is shown to the user."""


def _header(path: Path, fallback: str) -> str:
    """The leading comment block of an existing file, kept when it is rewritten."""
    if path.is_file():
        keep = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("#"):
                keep.append(line)
            else:
                break
        if keep:
            return "\n".join(keep) + "\n"
    return fallback


def _read_yaml(path: Path) -> dict:
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _write_yaml(path: Path, data: dict, header: str) -> None:
    """Rewrite a local config. Inline comments cannot be kept by a YAML dump, so
    the previous file is copied to <name>.bak first and the header is kept."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        path.with_name(path.name + ".bak").write_bytes(path.read_bytes())
    body = yaml.safe_dump(data, sort_keys=False, default_flow_style=None, width=100)
    path.write_text(header + body, encoding="utf-8")


def _example(path: Path) -> dict:
    return _read_yaml(path.with_name(path.name.replace(".yaml", ".example.yaml")))


def _point(p: Any, what: str) -> list[float]:
    try:
        u, v = float(p[0]), float(p[1])
    except Exception:
        raise CalibrationError(f"{what}: a point must be [x, y] pixel numbers") from None
    return [round(u, 1), round(v, 1)]


def read_frame_jpeg(video: Path, t_s: float) -> tuple[bytes, int, int]:
    if not video.is_file():
        raise CalibrationError(f"Video not found: {video.name}")
    cap = cv2.VideoCapture(str(video))
    try:
        if not cap.isOpened():
            raise CalibrationError(f"Cannot open video: {video.name}")
        cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t_s) * 1000.0)
        ok, frame = cap.read()
        if not ok:
            raise CalibrationError(f"No frame at {t_s:.2f} s in {video.name}")
    finally:
        cap.release()
    h, w = frame.shape[:2]
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise CalibrationError("Could not encode the frame")
    return buf.tobytes(), w, h


def clean_ground_spec(spec: dict) -> dict:
    """Validate a posted mapping spec and return it in the ground.yaml layout."""
    pts = []
    for p in spec.get("points") or []:
        role = p.get("role")
        if role not in ("fit", "check"):
            raise CalibrationError(f"point {p.get('id')}: role must be fit or check")
        m = p.get("m")
        if m is None or len(m) != 2 or m[0] is None or m[1] is None:
            raise CalibrationError(f"point {p.get('id')}: ground position in metres is missing")
        pts.append({"id": str(p.get("id")), "px": _point(p["px"], f"point {p.get('id')}"),
                    "m": [float(m[0]), float(m[1])], "role": role})
    dists = []
    for d in spec.get("check_distances") or []:
        dm = float(d["distance_m"])
        if dm <= 0:
            raise CalibrationError("a measured distance must be above zero")
        dists.append({"a_px": _point(d["a_px"], "distance start"), "b_px": _point(d["b_px"], "distance end"),
                      "distance_m": dm})
    zone = [_point(c, "zone corner") for c in spec.get("zone_px") or []]
    return {"zone_px": zone, "points": pts, "check_distances": dists}


def check_ground(spec: dict) -> dict:
    """Fit the mapping from the posted spec and report its error in metres."""
    clean = clean_ground_spec(spec)
    try:
        m = fit_mapping(str(spec.get("name") or "all"), clean)
    except ValueError as e:
        raise CalibrationError(str(e)) from None
    return {
        "fit_points": m.n_fit,
        "rms_fit_residual_m": round(m.rms_fit_residual_m, 3),
        "max_check_error_m": round(m.max_check_error_m, 3),
        "check_point_errors_m": {k: round(v, 3) for k, v in m.check_point_errors_m.items()},
        "check_distance_errors_m": [round(v, 3) for v in m.check_distance_errors_m],
    }


def _inside(m, px: list[float], what: str) -> None:
    if not m.contains(px[0], px[1]):
        raise CalibrationError(f"{what} is outside the valid area of the ground mapping, so it has no metres. "
                               "Make the valid area (step 1C) cover it and add a tape check there.")


def _saved_mapping():
    """The mapping in calibration/ground.yaml, refusing the example template."""
    data = _read_yaml(GROUND_FILE)
    maps = data.get("mappings") or {}
    if not maps or maps == _example(GROUND_FILE).get("mappings"):
        raise CalibrationError("Save the ground points first (step 1): metres come from them.")
    name, spec = next(iter(maps.items()))
    try:
        return fit_mapping(name, spec)
    except ValueError as e:
        raise CalibrationError(f"calibration/ground.yaml: {e}") from None


def _ground_sha() -> str:
    return sha256_file(GROUND_FILE)[:16] if GROUND_FILE.is_file() else ""


def measure(a_px, b_px) -> dict:
    """Ground distance between two clicked pixels, read through the SAVED mapping
    (derived value). Both points must lie inside the mapping's valid area."""
    m = _saved_mapping()
    a_px, b_px = _point(a_px, "start"), _point(b_px, "end")
    _inside(m, a_px, "The first point")
    _inside(m, b_px, "The second point")
    a, b = to_ground(m.h(), np.array([a_px, b_px], float))
    return {"distance_m": round(float(np.linalg.norm(a - b)), 2), "value_type": "derived",
            "max_check_error_m": round(m.max_check_error_m, 3), "ground_sha256": _ground_sha()}


def save_ground(payload: dict) -> dict:
    """Save one mapping (by name; other mappings in the file are kept), then
    recompute stop points saved from the page so they stay in the same frame."""
    spec = payload.get("mapping") or {}
    report = check_ground(spec)
    name = str(spec.get("name") or "all")
    clean = clean_ground_spec(spec)
    data = _read_yaml(GROUND_FILE)
    example = _example(GROUND_FILE)
    if data.get("mappings") == example.get("mappings"):
        data["mappings"] = {}                      # template placeholders are not kept
        if data.get("landmarks") == example.get("landmarks"):
            data.pop("landmarks", None)
    data.setdefault("mappings", {})[name] = clean
    _write_yaml(GROUND_FILE, data, "# Saved from the Calibrate page. Pixels are in the prepared video frame;\n"
                                   "# metres are what you measured on the road.\n")
    return {"saved": True, "report": report, "other_mappings": sorted(k for k in data["mappings"] if k != name),
            "stop_points": _recompute_stop_points()}


def _recompute_stop_points() -> dict:
    """Stop points saved with their pixel are re-read through the new mapping.
    One that falls outside the valid area is cleared, never extrapolated."""
    data = _read_yaml(DEFINITIONS_FILE)
    apps = data.get("approaches") or {}
    todo = {k: a for k, a in apps.items() if isinstance(a, dict) and a.get("stop_point_px")}
    if not todo:
        return {}
    m = _saved_mapping()
    out = {}
    for k, a in todo.items():
        px = a["stop_point_px"]
        if m.contains(px[0], px[1]):
            x, y = to_ground(m.h(), np.array([px], float))[0]
            a["stop_point_m"] = [round(float(x), 2), round(float(y), 2)]
            out[k] = "updated"
        else:
            a["stop_point_m"] = None
            out[k] = "cleared: outside the valid area, click it again"
        a["ground_sha256"] = _ground_sha()
    _write_yaml(DEFINITIONS_FILE, data, _header(DEFINITIONS_FILE, "# Operational definitions (O6).\n"))
    return out


def save_lines(payload: dict) -> dict:
    lines = []
    seen = set()
    for d in payload.get("lines") or []:
        name = str(d.get("name") or "").strip()
        if not name or name in seen:
            raise CalibrationError(f"line name missing or used twice: {name!r}")
        seen.add(name)
        if d.get("type") not in LINE_TYPES:
            raise CalibrationError(f"line {name}: type must be one of {LINE_TYPES}")
        if d.get("direction") not in DIRECTIONS:
            raise CalibrationError(f"line {name}: direction must be one of {DIRECTIONS}")
        if not d.get("approach"):
            raise CalibrationError(f"line {name}: approach is missing")
        ends = d.get("endpoints_px") or []
        if len(ends) != 2:
            raise CalibrationError(f"line {name}: needs two end points")
        lines.append({"name": name, "type": d["type"], "approach": str(d["approach"]),
                      "endpoints_px": [_point(ends[0], name), _point(ends[1], name)],
                      "direction": d["direction"]})
    if not lines:
        raise CalibrationError("no lines to save")
    old = _read_yaml(LINES_FILE)
    template = _example(LINES_FILE).get("movements") or []
    # Template movements and movements that point at a removed line are dropped, not kept.
    old_moves = [m for m in (old.get("movements") or []) if m not in template]
    moves = [m for m in old_moves if m.get("entry_line") in seen and m.get("exit_line") in seen]
    dropped = len(old.get("movements") or []) - len(moves)
    data = {"lines": lines}
    if moves:
        data["movements"] = moves
    _write_yaml(LINES_FILE, data, "# Saved from the Calibrate page. Pixels are in the prepared video frame.\n"
                                  "# direction: the side a counted vehicle comes from, walking from the first\n"
                                  "# end point to the second (left, right or both).\n")
    return {"saved": True, "lines": len(lines), "movements_kept": len(moves), "movements_dropped": dropped}


def _signal_head(v: Any) -> str | None:
    v = str(v or "").strip()
    return v or None


def save_zones(payload: dict) -> dict:
    """Approach areas (px), stop points and signal heads for delay and queue.
    Saved areas the page does not send are kept unless named in "remove".
    The stop point's metres come from the saved ground mapping, and its pixel
    is stored so it can be recomputed when the ground points change."""
    m = _saved_mapping()
    data = _read_yaml(DEFINITIONS_FILE)
    example = _example(DEFINITIONS_FILE).get("approaches") or {}
    out = {k: v for k, v in (data.get("approaches") or {}).items() if example.get(k) != v}   # drop placeholders
    for name in payload.get("remove") or []:
        out.pop(name, None)
    for name, a in (payload.get("approaches") or {}).items():
        zone = [_point(c, f"{name} area corner") for c in a.get("zone_px") or []]
        if len(zone) < 3:
            raise CalibrationError(f"{name}: the area needs at least 3 corners")
        stop = a.get("stop_point_px")
        if stop is None:
            raise CalibrationError(f"{name}: click the stop point")
        stop = _point(stop, f"{name} stop point")
        _inside(m, stop, f"The {name} stop point")
        head = _signal_head(a.get("signal_head"))
        if head is None:
            raise CalibrationError(f"{name}: type its signal head, as written in your signal log")
        x, y = to_ground(m.h(), np.array([stop], float))[0]
        out[name] = {"zone_px": zone, "stop_point_px": stop, "stop_point_m": [round(float(x), 2), round(float(y), 2)],
                     "signal_head": head, "ground_sha256": _ground_sha()}
    data["approaches"] = out
    _write_yaml(DEFINITIONS_FILE, data, _header(DEFINITIONS_FILE, "# Operational definitions (O6).\n"))
    return {"saved": True, "approaches": sorted(out)}


def save_width(approach: str, width_m: float, value_type: str, check_error_m: float | None = None,
               signal_head: Any = None) -> dict:
    """Road width at the stop line. value_type says where it came from: measured
    (tape on site) or derived (read through the ground mapping, with its error)."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", approach or ""):
        raise CalibrationError("bad approach name")
    if value_type not in ("measured", "derived"):
        raise CalibrationError("value_type must be measured or derived")
    if not (0.5 <= width_m <= 60):
        raise CalibrationError("width must be between 0.5 and 60 m")
    data = _read_yaml(INDICATORS_FILE)
    apps = data.get("approaches") or {}
    data["approaches"] = apps
    entry = dict(apps.get(approach) or {})
    entry["width_m"] = round(float(width_m), 2)
    entry["width_value_type"] = value_type
    if value_type == "derived":
        entry["width_check_error_m"] = check_error_m
        entry["width_ground_sha256"] = _ground_sha()
    else:
        entry.pop("width_check_error_m", None)
        entry.pop("width_ground_sha256", None)
    head = _signal_head(signal_head)
    if head:
        entry["signal_head"] = head
    entry.setdefault("signal_head", None)
    apps[approach] = entry
    _write_yaml(INDICATORS_FILE, data, _header(INDICATORS_FILE, "# Indicators config (O3).\n"))
    warn = None if entry["signal_head"] else f"{approach} has no signal head yet; capacity needs it."
    return {"saved": True, "approach": approach, "width_m": entry["width_m"], "value_type": value_type, "warning": warn}


def state() -> dict:
    """What is already saved. Values still equal to the example template are
    placeholders and are not offered as saved work."""
    videos = []
    for folder in (REPO_ROOT / "data" / "cfr", REPO_ROOT / "data" / "undistorted"):
        if folder.is_dir():
            videos += sorted(p.relative_to(REPO_ROOT).as_posix() for p in folder.glob("*.mp4"))
    ground = _read_yaml(GROUND_FILE)
    if ground.get("mappings") == _example(GROUND_FILE).get("mappings"):
        ground = {}
    example_lines = {l["name"]: l for l in (_example(LINES_FILE).get("lines") or [])}
    lines = [l for l in (_read_yaml(LINES_FILE).get("lines") or []) if example_lines.get(l.get("name")) != l]
    zones = _read_yaml(DEFINITIONS_FILE).get("approaches") or {}
    example_zones = _example(DEFINITIONS_FILE).get("approaches") or {}
    zones = {k: v for k, v in zones.items() if example_zones.get(k) != v}
    ind = _read_yaml(INDICATORS_FILE)
    return {"videos": videos, "ground": ground, "lines": lines, "zones": zones,
            "widths": {k: {"width_m": (v or {}).get("width_m"), "value_type": (v or {}).get("width_value_type"),
                           "signal_head": (v or {}).get("signal_head")}
                       for k, v in (ind.get("approaches") or {}).items()},
            "ground_mappings": sorted((ground.get("mappings") or {}).keys())}
