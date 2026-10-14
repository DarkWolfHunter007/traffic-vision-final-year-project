"""Editors for the hand-made inputs: settings, counting lines, ground points, phase log.

Every save is checked by the same loader the pipeline uses, so the app cannot
write a file the pipeline would refuse. Positions and distances come from the
user (clicked on a frame or measured on site); the app adds no values.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Body, HTTPException

from pattom.viewer.common import dump_yaml, inside, load_yaml_or_example, validated_write

SETTINGS = {
    "detection": ("configs/detection.yaml", "configs/detection.example.yaml"),
    "tracker": ("configs/tracker.yaml", "configs/tracker.example.yaml"),
}
LINES = ("configs/lines.yaml", "configs/lines.example.yaml")
GROUND = ("calibration/ground.yaml", "calibration/ground.example.yaml")
LINES_HEADER = """# Counting lines and movements, saved from the Pattom app (T18). Pixels are in the
# prepared video. "direction" is the side a counted vehicle comes from, seen walking
# from the first endpoint to the second."""
GROUND_HEADER = """# Ground points, saved from the Pattom app (T04, T48). px: pixel in the prepared frame;
# m: site coordinates in metres, measured on site. Check points are never used to fit."""


def _validate_settings(kind: str):
    def check(path: Path) -> None:
        if kind == "detection":
            from pattom.detection import DetectionConfig

            DetectionConfig.load(path)
        else:
            from pattom.tracking import TrackerConfig

            TrackerConfig.load(path)
    return check


def _validate_lines(path: Path) -> None:
    from pattom.counting import load_lines

    load_lines(path)


def _validate_ground(path: Path) -> None:
    from pattom.ground import GroundCalibration

    GroundCalibration.from_config(path)


def _ground_report(spec: dict[str, Any]) -> dict[str, Any]:
    from pattom.ground import fit_mapping

    out: dict[str, Any] = {}
    for name, m in (spec.get("mappings") or {}).items():
        try:
            fit = fit_mapping(name, m)
            out[name] = {"ok": True, "fit_points": fit.n_fit, "max_check_error_m": fit.max_check_error_m,
                         "check_point_errors_m": fit.check_point_errors_m,
                         "check_distance_errors_m": fit.check_distance_errors_m,
                         "rms_fit_residual_m": fit.rms_fit_residual_m}
        except Exception as e:
            out[name] = {"ok": False, "error": str(e)}
    return out


def router(root: Path) -> APIRouter:
    r = APIRouter(prefix="/api")

    # --- detection and tracker settings (YAML text) -----------------------

    @r.get("/settings/{kind}")
    def get_settings(kind: str) -> dict[str, Any]:
        if kind not in SETTINGS:
            raise HTTPException(404, f"unknown settings {kind!r}")
        path, example = SETTINGS[kind]
        p = root / path
        src = p if p.exists() else root / example
        return {"kind": kind, "path": path, "from_example": not p.exists(),
                "text": src.read_text(encoding="utf-8-sig") if src.exists() else ""}

    @r.put("/settings/{kind}")
    def put_settings(kind: str, body: dict[str, str] = Body(...)) -> dict[str, Any]:
        if kind not in SETTINGS:
            raise HTTPException(404, f"unknown settings {kind!r}")
        validated_write(inside(root, SETTINGS[kind][0]), body.get("text", ""), _validate_settings(kind))
        return get_settings(kind)

    # --- counting lines ---------------------------------------------------

    @r.get("/lines")
    def get_lines() -> dict[str, Any]:
        spec, from_example = load_yaml_or_example(root, *LINES)
        if from_example:  # the example's coordinates are placeholders; start empty
            spec = {}
        return {"spec": {"lines": spec.get("lines") or [], "movements": spec.get("movements") or []},
                "from_example": from_example, "path": LINES[0]}

    @r.put("/lines")
    def put_lines(spec: dict[str, Any] = Body(...)) -> dict[str, Any]:
        validated_write(inside(root, LINES[0]), dump_yaml(spec, LINES_HEADER), _validate_lines)
        return get_lines()

    # --- ground points ----------------------------------------------------

    @r.get("/ground")
    def get_ground() -> dict[str, Any]:
        spec, from_example = load_yaml_or_example(root, *GROUND)
        if from_example:  # the example's points are placeholders; start empty
            spec = {"mappings": {}, "landmarks": []}
        return {"spec": spec, "from_example": from_example, "path": GROUND[0], "report": _ground_report(spec)}

    @r.post("/ground/fit")
    def fit(spec: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return _ground_report(spec)

    @r.put("/ground")
    def put_ground(spec: dict[str, Any] = Body(...)) -> dict[str, Any]:
        validated_write(inside(root, GROUND[0]), dump_yaml(spec, GROUND_HEADER), _validate_ground)
        return get_ground()

    # --- signal phase log -------------------------------------------------

    def phase_path(slot: str) -> Path:
        return inside(root, root / "runs" / slot / "phase_log.csv")

    @r.get("/phases/{slot}")
    def get_phases(slot: str) -> dict[str, Any]:
        p = phase_path(slot)
        rows = []
        if p.exists():
            with open(p, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        return {"slot": slot, "path": p.relative_to(root.resolve()).as_posix(), "rows": rows}

    @r.put("/phases/{slot}")
    def put_phases(slot: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        from pattom.phases import PHASE_FIELDS, cycles, read_phase_log

        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=PHASE_FIELDS, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        def order(row: dict) -> tuple[float, str]:
            try:
                return float(row.get("time_s", "")), str(row.get("signal_head", ""))
            except ValueError:
                return float("inf"), ""  # the loader reports the bad time

        for row in sorted(body.get("rows") or [], key=order):
            w.writerow({**row, "slot": slot})
        validated_write(phase_path(slot), buf.getvalue(), lambda path: read_phase_log(path, slot))
        result = get_phases(slot)
        result["cycles"] = cycles(read_phase_log(phase_path(slot), slot))
        return result

    @r.post("/phases/{slot}/check")
    def check_phases(slot: str) -> dict[str, Any]:
        from pattom.phases import cycles, read_phase_log

        p = phase_path(slot)
        if not p.exists():
            raise HTTPException(404, "no phase log saved for this slot")
        try:
            return {"cycles": cycles(read_phase_log(p, slot))}
        except ValueError as e:
            raise HTTPException(422, str(e)) from None

    # --- YAML preview (for the page's "show file" panels) -----------------

    @r.post("/yaml")
    def to_yaml(spec: dict[str, Any] = Body(...)) -> dict[str, str]:
        return {"text": yaml.safe_dump(spec, sort_keys=False, default_flow_style=None, width=110)}

    return r
