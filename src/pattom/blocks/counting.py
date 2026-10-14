"""F Counting: crossings, movements and interval counts (FR-09, T18)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pattom.harness.block import Block, RunContext
from pattom.harness.registry import register_block


@register_block
class Count(Block):
    name = "count"
    component = "F"
    title = "Line crossings and interval counts"
    inputs = {"tracks": "tracks"}
    outputs = ("crossings", "interval_counts")
    params = {"lines": "counting lines (default configs/lines.yaml)",
              "interval_s": "interval length in s (default 900)",
              "offset_s": "start of this file within its slot (default 0)"}
    tasks = ("T18",)
    note = "Line placement waits on O9 (free lefts) and O10 (west approach)."

    def run(self, ctx: RunContext, inputs: dict[str, Path], params: dict[str, Any]) -> dict[str, Path]:
        from pattom.counting import run_counting

        out = run_counting(inputs["tracks"], ctx.resolve(params.get("lines", "configs/lines.yaml")),
                           float(params.get("interval_s", 900.0)), float(params.get("offset_s", 0.0)))
        return {"crossings": out.parent / "crossings.csv", "interval_counts": out}
