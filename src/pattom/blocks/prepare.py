"""B Preparation: constant frame rate, lens calibration, undistortion (FR-03)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pattom.harness.block import Block, RunContext
from pattom.harness.registry import register_block


@register_block
class CFR(Block):
    name = "cfr"
    component = "B"
    title = "Constant-frame-rate copy"
    inputs = {"video": "video.raw"}
    outputs = ("video.cfr",)
    params = {"fps": "output frame rate (default 30)", "out": "output file (default data/cfr/<name>.mp4)"}
    tasks = ("T08",)

    def run(self, ctx: RunContext, inputs: dict[str, Path], params: dict[str, Any]) -> dict[str, Path]:
        from pattom.prepare import to_cfr

        src = inputs["video"]
        out = ctx.resolve(params.get("out", f"data/cfr/{src.stem}.mp4"))
        to_cfr(src, out, float(params.get("fps", 30.0)), ctx.slot)
        return {"video.cfr": out}


@register_block
class CalibrateLens(Block):
    name = "calibrate-lens"
    component = "B"
    title = "Lens calibration from a checkerboard clip"
    inputs = {"video": "video.checkerboard"}
    outputs = ("lens",)
    params = {"cols": "inner corners across", "rows": "inner corners down", "square_mm": "square size",
              "every": "seconds between sampled frames (default 0.5)",
              "out": "output file (default calibration/lens.json)"}
    required_params = ("cols", "rows", "square_mm")
    tasks = ("T09",)

    def run(self, ctx: RunContext, inputs: dict[str, Path], params: dict[str, Any]) -> dict[str, Path]:
        from pattom.prepare import calibrate_lens, sample_frames
        from pattom.runmeta import sha256_file

        video = inputs["video"]
        lens = calibrate_lens(
            sample_frames(video, float(params.get("every", 0.5))),
            (int(params["cols"]), int(params["rows"])),
            float(params["square_mm"]),
            source_video=str(video),
            source_sha256=sha256_file(video),
        )
        return {"lens": lens.save(ctx.resolve(params.get("out", "calibration/lens.json")))}


@register_block
class Undistort(Block):
    name = "undistort"
    component = "B"
    title = "Undistorted copy"
    inputs = {"video": "video.cfr", "lens": "lens"}
    outputs = ("video.undistorted",)
    params = {"out": "output file (default data/undistorted/<name>.mp4)"}
    tasks = ("T10",)

    def run(self, ctx: RunContext, inputs: dict[str, Path], params: dict[str, Any]) -> dict[str, Path]:
        from pattom.prepare import LensCalibration, undistort_video

        src = inputs["video"]
        out = ctx.resolve(params.get("out", f"data/undistorted/{src.stem}.mp4"))
        undistort_video(src, out, LensCalibration.load(inputs["lens"]), ctx.slot)
        return {"video.undistorted": out}
