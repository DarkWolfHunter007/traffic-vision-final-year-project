"""F side inputs: pixel-to-ground mapping and camera drift (FR-24, T48)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pattom.harness.block import Block, RunContext
from pattom.harness.registry import register_block


@register_block
class GroundMap(Block):
    name = "ground-map"
    component = "F"
    title = "Ground mapping of track points"
    inputs = {"tracks": "tracks"}
    outputs = ("tracks.ground", "ground_report")
    params = {"config": "ground points (default calibration/ground.yaml)"}
    tasks = ("T48",)
    note = "Fills ground_x_m / ground_y_m in tracks.csv; reports the check error in metres."

    def run(self, ctx: RunContext, inputs: dict[str, Path], params: dict[str, Any]) -> dict[str, Path]:
        from pattom.ground import GroundCalibration, map_tracks

        cal = GroundCalibration.from_config(ctx.resolve(params.get("config", "calibration/ground.yaml")))
        tracks = map_tracks(inputs["tracks"], cal)
        report = tracks.parent / "ground_report.json"
        report.write_text(json.dumps(cal.report(), indent=2) + "\n", encoding="utf-8")
        return {"tracks.ground": tracks, "ground_report": report}


@register_block
class Drift(Block):
    name = "drift"
    component = "F"
    title = "Camera drift check"
    inputs = {"video": "video.undistorted"}
    outputs = ("drift",)
    params = {"config": "landmarks (default calibration/ground.yaml)",
              "every": "seconds between checked frames (default 10)",
              "out": "output file (default runs/<slot>/<video>/drift.json)"}
    tasks = ("T48",)
    note = "Reports landmark shifts in pixels; the tolerance is agreed with the guide."

    def run(self, ctx: RunContext, inputs: dict[str, Path], params: dict[str, Any]) -> dict[str, Path]:
        import yaml

        from pattom.ground import drift_check, write_drift
        from pattom.prepare import sample_frames

        video = inputs["video"]
        spec = yaml.safe_load(ctx.resolve(params.get("config", "calibration/ground.yaml")).read_text("utf-8"))
        every = float(params.get("every", 10.0))
        frames = sample_frames(video, every)
        reference = next(frames)
        samples = drift_check(((i * every, f) for i, f in enumerate(frames, start=1)), reference,
                              (spec or {}).get("landmarks") or [])
        out = ctx.resolve(params.get("out", f"runs/{ctx.slot}/{video.stem}/drift.json"))
        return {"drift": write_drift(samples, out)}
