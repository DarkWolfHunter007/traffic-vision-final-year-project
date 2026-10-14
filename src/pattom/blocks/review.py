"""E Review: flagged frames for checking and relabelling. The labelling itself is on the app's Review page."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pattom.harness.block import Block, RunContext
from pattom.harness.registry import register_block


@register_block
class Review(Block):
    name = "review"
    component = "E"
    title = "Review queue: flagged frames to check and relabel"
    inputs = {"tracks": "tracks", "track_summary": "track_summary"}
    outputs = ("review_queue",)
    params = {"low_confidence": "flag a track whose weakest box is below this confidence",
              "edge_margin_px": "a track ending farther than this from the frame edge has vanished",
              "random_frames": "number of random frames added (confidence is not accuracy)",
              "seed": "seed for the random sample",
              "min_gap_s": "flagged frames are kept at least this far apart, s",
              "hard_zones": "optional [{name, polygon_px: [[u, v], ...]}] (far arm, behind cables)"}
    required_params = ("low_confidence", "edge_margin_px", "random_frames", "seed", "min_gap_s")
    tasks = ("T45", "T15")
    note = "Open the Review page to correct the flagged frames; labels go to labels/<slot>/<video>/ in YOLO format."

    def run(self, ctx: RunContext, inputs: dict[str, Path], params: dict[str, Any]) -> dict[str, Path]:
        from pattom.review import flag_frames

        meta = json.loads(inputs["tracks"].with_suffix(".run.json").read_text(encoding="utf-8"))
        det = inputs["tracks"].parent / "detections.run.json"
        frames = json.loads(det.read_text(encoding="utf-8"))["parameters"].get("frames_read") if det.exists() else None
        end = frames / float(meta["fps"]) if frames else None
        out = flag_frames(inputs["tracks"], inputs["track_summary"], ctx.slot, params, inputs["tracks"].parent,
                          (meta["width"], meta["height"]), end, float(meta["fps"]))
        return {"review_queue": out}
