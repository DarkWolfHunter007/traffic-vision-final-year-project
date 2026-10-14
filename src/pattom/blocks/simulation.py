"""L SUMO set-up and runs; M comparison. Only the existing case and the MCE winner (D1)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pattom.harness.block import Block, RunContext
from pattom.harness.registry import register_block


def _sumo_dir(ctx: RunContext) -> Path:
    d = ctx.resolve(f"sumo/{ctx.slot}")
    d.mkdir(parents=True, exist_ok=True)
    return d


@register_block
class SumoInputs(Block):
    name = "sumo-inputs"
    component = "L"
    title = "SUMO network, demand and signal plans (existing and selected alternative)"
    inputs = {"interval_counts": "interval_counts", "alternatives": "alternatives",
              "selected_alternative": "selected_alternative"}
    outputs = ("sumo_inputs",)
    params = {"approach_groups": "approach -> phase group, e.g. {north: NS, east: EW}",
              "phase_order": "phase groups in signal order, e.g. [NS, EW]",
              "all_red_s": "all-red time after each phase, s (measured; 0 if none)",
              "demand_line_type": "arrival or stop_line counts as demand",
              "unknown_movement": "exclude or proportional (counts without a known movement)",
              "network": "site network file (default configs/sumo_network.yaml)",
              "lines": "counting lines with movements (default configs/lines.yaml)"}
    required_params = ("approach_groups", "phase_order", "all_red_s", "demand_line_type", "unknown_movement")
    tasks = ("T31", "T32")
    waits_on = ("O9",)
    note = "Built from the site layout and counts on this PC; nothing is downloaded. Uses SUMO's netconvert."

    def run(self, ctx: RunContext, inputs: dict[str, Path], params: dict[str, Any]) -> dict[str, Path]:
        from pattom.sumo import build_inputs

        out = build_inputs(inputs["interval_counts"], inputs["alternatives"], inputs["selected_alternative"],
                           ctx.resolve(params.get("lines", "configs/lines.yaml")),
                           ctx.resolve(params.get("network", "configs/sumo_network.yaml")), ctx.slot, params,
                           _sumo_dir(ctx))
        return {"sumo_inputs": out}


@register_block
class SumoRun(Block):
    name = "sumo-run"
    component = "L"
    title = "SUMO runs: existing case and the selected alternative, same seeds"
    inputs = {"sumo_inputs": "sumo_inputs"}
    outputs = ("sumo_results",)
    params = {"seeds": "random seeds chosen before the runs, the same for both cases, e.g. [11, 23, 37, 41, 59]",
              "warmup_s": "warm-up excluded from the results, s"}
    required_params = ("seeds", "warmup_s")
    tasks = ("T33", "T34", "T35")
    waits_on = ("O14",)
    note = "Simulated values, reported apart from the video measurements and never used in the MCE (D1)."

    def run(self, ctx: RunContext, inputs: dict[str, Path], params: dict[str, Any]) -> dict[str, Path]:
        from pattom.sumo import run_cases

        return {"sumo_results": run_cases(inputs["sumo_inputs"], ctx.slot, params, inputs["sumo_inputs"].parent,
                                          log=ctx.log)}


@register_block
class Comparison(Block):
    name = "comparison"
    component = "M"
    title = "Existing vs selected alternative"
    inputs = {"sumo_results": "sumo_results", "stopped_delay": "stopped_delay", "queue": "queue"}
    outputs = ("comparison",)
    params = {"emission_method": "none or registered_idle_factors (O18)",
              "class_fuel": "for registered_idle_factors: vehicle type -> {idle_row, fuel}",
              "calibration_tolerance": "optional relative tolerance for the existing case vs video (O14)"}
    required_params = ("emission_method",)
    tasks = ("T36", "T37")
    waits_on = ("O18",)
    note = "Mean and spread over the seeds. SUMO emissions are a relative comparison only (D7)."

    def run(self, ctx: RunContext, inputs: dict[str, Path], params: dict[str, Any]) -> dict[str, Path]:
        from pattom.sumo import compare_cases

        return {"comparison": compare_cases(inputs["sumo_results"], inputs["stopped_delay"], inputs["queue"], ctx.slot,
                                            params, inputs["sumo_results"].parent)}
