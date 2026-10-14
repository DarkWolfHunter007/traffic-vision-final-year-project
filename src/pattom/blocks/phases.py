"""F Signal phases read from the footage (FR-10, T19)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pattom.harness.block import Block, RunContext
from pattom.harness.registry import register_block


@register_block
class SignalPhases(Block):
    name = "signal-phases"
    component = "F"
    title = "Signal phases and cycles"
    inputs = {"phase_log": "phase_log"}
    outputs = ("signal_phases", "signal_cycles")
    params = {"out_dir": "output folder (default runs/<slot>/signals)"}
    tasks = ("T19",)
    note = "The phase log is typed by the user from playback (measured)."

    def run(self, ctx: RunContext, inputs: dict[str, Path], params: dict[str, Any]) -> dict[str, Path]:
        from pattom.phases import run_phases

        out_dir = ctx.resolve(params.get("out_dir", f"runs/{ctx.slot}/signals"))
        phases, cyc = run_phases(inputs["phase_log"], ctx.slot, out_dir)
        return {"signal_phases": phases, "signal_cycles": cyc}
