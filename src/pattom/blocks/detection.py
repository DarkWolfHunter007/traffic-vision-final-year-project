"""C Detection: YOLO boxes per frame. YOLO only detects; it computes no traffic values."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pattom.harness.block import Block, RunContext
from pattom.harness.registry import register_block


@register_block
class Detect(Block):
    name = "detect"
    component = "C"
    title = "YOLO detection"
    inputs = {"video": "video.undistorted"}
    outputs = ("detections",)
    params = {"config": "detection settings (default configs/detection.yaml)"}
    tasks = ("T11", "T16")
    note = "Needs the detect extra and the weights in models/."

    def run(self, ctx: RunContext, inputs: dict[str, Path], params: dict[str, Any]) -> dict[str, Path]:
        from pattom.detection import DetectionConfig, run_detection

        cfg = DetectionConfig.load(ctx.resolve(params.get("config", "configs/detection.yaml")))
        return {"detections": run_detection(inputs["video"], ctx.slot, cfg, progress=ctx.log)}
