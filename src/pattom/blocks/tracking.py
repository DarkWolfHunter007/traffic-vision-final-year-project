"""D Tracking: links detections over time."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pattom.harness.block import Block, RunContext
from pattom.harness.registry import register_block


@register_block
class Track(Block):
    name = "track"
    component = "D"
    title = "ByteTrack tracking"
    inputs = {"detections": "detections"}
    outputs = ("tracks", "track_summary")
    params = {"config": "tracker settings (default configs/tracker.yaml)"}
    tasks = ("T11", "T16")
    waits_on = ()
    note = "Tracker choice is open (O7); ByteTrack is the one implemented."

    def run(self, ctx: RunContext, inputs: dict[str, Path], params: dict[str, Any]) -> dict[str, Path]:
        from pattom.tracking import TrackerConfig, run_tracking

        tracks = run_tracking(inputs["detections"],
                              TrackerConfig.load(ctx.resolve(params.get("config", "configs/tracker.yaml"))))
        return {"tracks": tracks, "track_summary": tracks.parent / "track_summary.csv"}
